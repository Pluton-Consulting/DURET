#!/usr/bin/env python3
"""Livraison contrôlée sur un VPS existant, sans réinitialiser ses données.

Aucune clé existante n'est remplacée. Les volumes réels sont comparés à la
configuration avant toute mutation. Les migrations et leurs marques passent
ensemble en transaction. Les données protégées sont comparées avant de
redémarrer les services. Les journaux techniques restent privés sur le VPS.
"""
import argparse,contextlib,datetime,fcntl,hashlib,json,os,re,secrets,shutil,subprocess,sys,tempfile
from pathlib import Path
from urllib.parse import urlsplit,unquote

PROTEGEES=('users','threads','messages','connexions_google','cles_api','reglages',
           'mail_signatures','sessions_appareil','profils_utilisateur','consignes',
           'lecons','trames','documents','document_metadata','agent_tasks','validations',
           'skills','conversation_memoire','connexions_microsoft','connexions_imap','mail_brouillons')
class Refus(RuntimeError):pass

def empreinte(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def ident(n):return '"'+str(n).replace('"','""')+'"'
def literal(n):return "'"+str(n).replace("'","''")+"'"

def projection(table,colonnes):
    # Comparer seulement les colonnes d'avant : une colonne additive n'est pas
    # une altération des anciennes données. Pas de contenu personnel exporté.
    valeurs=','.join(ident(c) for c in colonnes)
    return ("SELECT json_build_object('lignes',count(*),'empreinte',md5(coalesce("
            "string_agg(h,'' ORDER BY h),''))) FROM (SELECT md5(jsonb_build_array("
            +valeurs+")::text) h FROM "+ident(table)+") protegees")

def fichiers_secrets(root):
    files=[root/'.env']
    d=root/'backend/secrets'
    if d.exists():files.extend(p for p in d.rglob('*') if p.is_file())
    return {str(p.relative_to(root)):empreinte(p) for p in files if p.is_file()}

def preparer_secret_manquant(root,config):
    """Ajouter uniquement le secret interne manquant, jamais les clés métier."""
    env=config['services']['backend'].get('environment',{})
    if env.get('BROWSER_WORKER_SECRET'):return False
    p=root/'.env';brut=p.read_bytes()
    # Si la variable est explicitement définie, même vide, la remplacer serait
    # ambiguë (doublon Compose) : seul cet emplacement vide est complété.
    lignes=brut.decode('utf-8').splitlines(keepends=True)
    positions=[i for i,l in enumerate(lignes) if re.match(r'^\s*(?:export\s+)?BROWSER_WORKER_SECRET\s*=',l)]
    if len(positions)>1:raise Refus('BROWSER_WORKER_SECRET est défini plusieurs fois ; aucun fichier modifié.')
    valeur=secrets.token_urlsafe(48)
    if positions:
        i=positions[0];contenu=lignes[i].split('=',1)[1].strip()
        if contenu not in ('',"''",'""'):
            raise Refus('Le secret navigateur présent ne se résout pas ; aucune clé remplacée.')
        lignes[i]='BROWSER_WORKER_SECRET='+valeur+'\n'
        nouveau=''.join(lignes).encode()
    else:nouveau=brut+(b'\n' if brut and not brut.endswith(b'\n') else b'')+b'BROWSER_WORKER_SECRET='+valeur.encode()+b'\n'
    fd,nom=tempfile.mkstemp(prefix='.env-livraison-',dir=root)
    try:
        with os.fdopen(fd,'wb') as f:f.write(nouveau);f.flush();os.fsync(f.fileno())
        os.chmod(nom,p.stat().st_mode & 0o777)
        os.replace(nom,p)
    finally:
        if os.path.exists(nom):os.unlink(nom)
    return True

class Livraison:
    def __init__(self,root,ancienne_racine=None,configuration_retour=None):
        self.root=Path(root).resolve();self.journal=None
        self.ancienne_racine=Path(ancienne_racine).resolve() if ancienne_racine else None
        self.configuration_retour=Path(configuration_retour).resolve() if configuration_retour else None
        # Charger le helper à côté du script, même lors d'un import par recette.
        import importlib.util
        spec=importlib.util.spec_from_file_location('compose_livraison',Path(__file__).with_name('compose_livraison.py'))
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        self.compose=['docker','compose']
        for nom in module.fichiers(self.root):self.compose+=['-f',nom]
        self.config={};self.etat={};self.arretes=[];self.bascule=False
    def commande(self,args,entree=None):
        r=subprocess.run(args,cwd=self.root,input=entree,capture_output=True,text=True)
        if r.returncode:
            if self.journal:
                with (self.journal/'erreurs.log').open('a') as f:f.write(r.stderr+'\n')
            raise Refus('Commande en échec : '+ ' '.join(args[:4]) +'. Détails dans le journal privé de livraison.')
        return r.stdout.strip()
    def dc(self,*args,entree=None):return self.commande(self.compose+list(args),entree)
    def psql(self,sql):
        env=self.config['services']['postgres']['environment']
        return self.dc('exec','-T','postgres','psql','-X','-q','-tA','-v','ON_ERROR_STOP=1',
                       '-U',env['POSTGRES_USER'],'-d',env['POSTGRES_DB'],entree=sql+'\n')
    def charger_config(self):
        self.config=json.loads(self.dc('config','--format','json'))
        return self.config
    def verifier(self):
        if not (self.root/'.env').is_file():raise Refus('.env absent : une mise à jour ne doit pas inventer les clés existantes.')
        config=self.charger_config();services=config['services'];pg=services['postgres']['environment']
        db=urlsplit(services['backend']['environment'].get('DATABASE_URL','').replace('postgresql+asyncpg://','postgresql://'))
        if db.hostname!='postgres' or (db.port or 5432)!=5432:
            raise Refus('DATABASE_URL doit viser le service PostgreSQL existant de cette configuration ; base externe non modifiée.')
        if unquote(db.path.lstrip('/'))!=pg.get('POSTGRES_DB'):
            raise Refus('DATABASE_URL et POSTGRES_DB ne désignent pas la même base ; aucune mutation.')
        if unquote(db.username or '')!=pg.get('POSTGRES_USER') or unquote(db.password or '')!=pg.get('POSTGRES_PASSWORD'):
            raise Refus('DATABASE_URL et les identifiants PostgreSQL ne concordent pas ; aucune mutation.')
        if not all(pg.get(k) for k in ('POSTGRES_USER','POSTGRES_DB','POSTGRES_PASSWORD')):
            raise Refus('Configuration PostgreSQL existante incomplète ; aucune mutation.')
        actifs=self.commande(['docker','ps','--filter','label=com.docker.compose.project='+config['name'],'--format','{{.Label "com.docker.compose.service"}}']).split()
        if set(actifs)-set(services):raise Refus('Des services actifs supplémentaires existent dans ce projet ; préserver leur topologie avant la livraison.')
        captures={}
        for nom in services:
            ids=self.dc('ps','-aq',nom).split()
            if len(ids)>1:raise Refus('Plusieurs conteneurs pour '+nom+' : topologie à vérifier avant mise à jour.')
            if ids:captures[nom]=json.loads(self.commande(['docker','inspect',ids[0]]))[0]
        if 'postgres' not in captures:
            raise Refus('PostgreSQL existant introuvable pour ce projet Compose. Refus de créer une base vide.')
        if not captures['postgres']['State'].get('Running'):
            raise Refus('La base existante est arrêtée : la démarrer avec sa configuration actuelle avant le contrôle.')
        volumes={}
        for service,cible in (('postgres','/var/lib/postgresql/data'),('backend','/documents')):
            conteneur=captures.get(service)
            if not conteneur:raise Refus('Conteneur existant '+service+' introuvable : volume non vérifiable.')
            montage=next((m for m in conteneur.get('Mounts',[]) if m['Destination']==cible),None)
            voulu=next((m for m in services[service].get('volumes',[]) if m['target']==cible),None)
            if not montage or not voulu or montage.get('Type')!='volume' or voulu.get('type')!='volume':
                raise Refus('Volume persistant non reconnu pour '+service+' : aucune mutation.')
            attendu=config['volumes'][voulu['source']]['name']
            if montage.get('Name')!=attendu:raise Refus('La livraison changerait le volume de '+service+' ; arrêt avant création.')
            self.commande(['docker','volume','inspect',attendu]);volumes[service]=attendu
        navigateur=captures.get('browser-worker')
        if navigateur:
            ancien_volume=next((m for m in navigateur.get('Mounts',[]) if m['Destination']=='/sessions' and m.get('Type')=='volume'),None)
            nouveau_volume=next((m for m in services.get('browser-worker',{}).get('volumes',[]) if m['target']=='/sessions' and m.get('type')=='volume'),None)
            if ancien_volume and (not nouveau_volume or ancien_volume['Name']!=config['volumes'][nouveau_volume['source']]['name']):
                raise Refus('Le volume des sessions navigateur changerait ; aucune mutation.')
        # Conserver les certificats HTTPS et leur configuration dans les mêmes volumes.
        if 'caddy' in captures:
            for montage in captures['caddy'].get('Mounts',[]):
                if montage.get('Type')!='volume':continue
                voulu=next((v for v in services['caddy'].get('volumes',[]) if v['target']==montage['Destination'] and v.get('type')=='volume'),None)
                if not voulu or config['volumes'][voulu['source']]['name']!=montage['Name']:
                    raise Refus('Un volume HTTPS existant changerait ; aucune mutation.')
        # Sans imprimer aucune valeur, refuser les clés déjà en service qui
        # seraient remplacées par ce checkout (sauf réglages non secrets).
        ancien=dict(x.split('=',1) for x in captures['backend']['Config'].get('Env',[]) if '=' in x)
        nouveau=services['backend'].get('environment',{})
        for k,v in ancien.items():
            # GPG_KEY est la clé publique de signature de l’image officielle Python.
            if k!='GPG_KEY' and v and re.search(r'(?:_KEY|_TOKEN|_PASSWORD|_SECRET|_SECRET_KEY|_CLE)$',k):
                if nouveau.get(k)!=v:raise Refus('La clé existante '+k+' serait changée ou retirée : arrêt sans modification.')
        self.psql('SELECT 1;')
        self.etat={'projet':config['name'],'volumes':volumes,'secrets':fichiers_secrets(self.root),
                   'conteneurs':{n:{'id':c['Id'],'image':c['Image'],'actif':c['State'].get('Running',False)} for n,c in captures.items()}}
        navigateur=captures.get('browser-worker')
        if navigateur:
            env_browser=dict(x.split('=',1) for x in navigateur['Config'].get('Env',[]) if '=' in x)
            if env_browser.get('BROWSER_SESSIONS_DIR')=='/tmp/sessions':
                self.etat['sessions_temporaires']=navigateur['Id']
        print('Précontrôle OK : base existante, volumes identiques et clés conservées.')
        return self.etat
    def donnees(self,colonnes=None):
        if colonnes is None:
            sql="SELECT coalesce(json_object_agg(table_name,cols),'{}'::json) FROM (SELECT table_name,json_agg(column_name ORDER BY ordinal_position) cols FROM information_schema.columns WHERE table_schema='public' AND table_name IN ("+','.join(literal(t) for t in PROTEGEES)+") GROUP BY table_name) c"
            colonnes=json.loads(self.psql(sql))
        return {'colonnes':colonnes,'tables':{t:json.loads(self.psql(projection(t,cs)+';')) for t,cs in colonnes.items()}}
    def migrations(self):
        dossier=self.root/'backend/database/migrations'
        self.psql('CREATE TABLE IF NOT EXISTS schema_migrations(filename TEXT PRIMARY KEY, applied_at TIMESTAMPTZ DEFAULT now());')
        marquees=set(self.psql('SELECT filename FROM schema_migrations;').split())
        attendus={}
        for l in (dossier/'attendus.tsv').read_text().splitlines():
            if l and not l.startswith('#') and '\t' in l:
                nom,requete=l.split('\t',1);attendus[nom]=requete
        # Même procédure de reprise du suivi historique, sans le vider.
        baseline=not marquees and self.psql("SELECT to_regclass('public.users') IS NOT NULL;")=='t'
        sql=["SELECT pg_advisory_lock(hashtext(current_database() || ':livraison'));",'SET lock_timeout = \'30s\';']
        for p in sorted(dossier.glob('[0-9]*.sql')):
            if p.name in marquees:continue
            presente=baseline and p.name in attendus and self.psql(attendus[p.name])=='t'
            sql+=['BEGIN;']
            if not presente:sql+=[p.read_text()]
            sql += ['INSERT INTO schema_migrations(filename) VALUES ('+literal(p.name)+') ON CONFLICT DO NOTHING;','COMMIT;']
        self.psql('\n'.join(sql))
        for nom,q in attendus.items():
            if (dossier/nom).exists() and self.psql(q)!='t':raise Refus('Objet attendu absent après migration : '+nom)
        print('Migrations appliquées et objets attendus vérifiés.')
    def reprendre_anciens(self):
        if self.bascule and self.configuration_retour:
            self.commande(['docker','compose','-p',self.etat['projet'],'--project-directory',str(self.ancienne_racine or self.root),'-f',str(self.configuration_retour),'up','-d','--no-build','--pull','never'])
            self.commande(['docker','compose','-p',self.etat['projet'],'--project-directory',str(self.ancienne_racine or self.root),'-f',str(self.configuration_retour),'restart','nginx'])
            return
        if self.bascule:
            config={'services':{n:{'image':c['image']} for n,c in self.etat['conteneurs'].items() if n in ('backend','frontend','browser-worker')}}
            p=self.journal/'images-precedentes.json';p.write_text(json.dumps(config))
            self.commande(self.compose+['-f',str(p),'up','-d','--no-build','--pull','never'])
            self.dc('restart','nginx')
        else:
            for n in self.arretes:
                if self.etat['conteneurs'][n]['actif']:self.commande(['docker','start',self.etat['conteneurs'][n]['id']])
    def conserver_sessions(self):
        if 'browser-worker' not in self.config.get('services',{}):return
        conteneur=self.etat.get('sessions_temporaires')
        copie=self.journal/'sessions-avant';copie.mkdir(mode=0o700)
        r=subprocess.run(['docker','cp',conteneur+':/tmp/sessions/.',str(copie)],capture_output=True,text=True) if conteneur else None
        if r is not None and r.returncode:
            # Aucun parcours de connexion n'a peut-être encore créé le dossier.
            if 'could not find' not in r.stderr.lower() and 'no such file' not in r.stderr.lower():
                raise Refus('Impossible de préserver les sessions temporaires du navigateur ; ancienne application conservée.')
        service=self.config['services']['browser-worker']
        volume=next((v for v in service.get('volumes',[]) if v.get('target')=='/sessions' and v.get('type')=='volume'),None)
        if not volume:raise Refus('Volume de sessions navigateur absent de la configuration.')
        nom_volume=self.config['volumes'][volume['source']]['name']
        image=service.get('image') or self.config['name']+'-browser-worker'
        if not image or '\n' in image:raise Refus('Image navigateur ambiguë pour préserver les sessions.')
        # Aucune clé ni aucun montage de connecteur dans ce conteneur de copie.
        self.commande(['docker','run','--rm','--user','root','--volume',nom_volume+':/sessions','--volume',str(copie)+':/sessions-avant:ro',
                '--entrypoint','/app/.venv/bin/python',image,'-c',
                "import pathlib,shutil,pwd,os; p=pathlib.Path('/sessions'); p.mkdir(exist_ok=True); shutil.copytree('/sessions-avant',p,dirs_exist_ok=True); u=pwd.getpwnam('browseruse'); os.chown(p,u.pw_uid,u.pw_gid); [(os.chown(f,u.pw_uid,u.pw_gid),os.chmod(f,0o700 if f.is_dir() else 0o600)) for f in p.rglob('*') if not f.is_symlink()]"])
        print('Sessions navigateur conservées dans le volume persistant.')

    def appliquer(self):
        os.umask(0o077)
        dossier=self.root/'.livraisons';dossier.mkdir(mode=0o700,exist_ok=True)
        self.charger_config()
        chemin=Path(tempfile.gettempdir())/('infra-ia-livraison-'+hashlib.sha256(self.config['name'].encode()).hexdigest()+'.lock')
        fd=os.open(chemin,os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0),0o600)
        with os.fdopen(fd,'a') as verrou:
            try:fcntl.flock(verrou,fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:raise Refus('Une livraison est déjà en cours.')
            self.verifier()
            self.journal=Path(tempfile.mkdtemp(prefix=datetime.datetime.now().strftime('%Y%m%d-%H%M%S-'),dir=dossier))
            (self.journal/'avant.json').write_text(json.dumps(self.etat,indent=2))
            shutil.copy2(self.root/'.env',self.journal/'env-avant')
            # Construire ne recrée aucun conteneur. Les anciennes images restent
            # référencées par leurs conteneurs et par le journal de retour arrière.
            manifeste=self.root/'LIVRAISON.json'
            if manifeste.is_file():
                m=json.loads(manifeste.read_text());commit=m.get('revision_base','archive');branche='livraison-'+m.get('version','archive')
                trace='manifeste_sha256='+empreinte(manifeste)+'\n'
            else:
                try:
                    commit=self.commande(['git','rev-parse','HEAD']);branche=self.commande(['git','rev-parse','--abbrev-ref','HEAD'])
                except Refus:commit=branche='archive'
                trace=''
            (self.root/'backend/.version').write_text('commit='+commit+'\nbranche='+branche+'\n'+trace+'livre_le='+datetime.datetime.now(datetime.timezone.utc).isoformat()+'\n')
            for nom,conteneur in self.etat.get('conteneurs',{}).items():
                if conteneur.get('image'):
                    reference='infra-ia-retour/'+self.etat['projet']+'/'+nom+':'+conteneur['image'].split(':')[-1][:32]
                    self.commande(['docker','image','tag',conteneur['image'],reference])
                    conteneur['image']=reference
            print('Construction des images avant l’interruption des services…')
            self.commande(self.compose[:2]+['--parallel','1']+self.compose[2:]+['build']+[n for n in ('backend','frontend','browser-worker') if n in self.config['services']])
            try:
                for n in ('backend','browser-worker'):
                    if n in self.etat['conteneurs']:
                        self.dc('stop','-t','60',n);self.arretes.append(n)
                if self.ancienne_racine:
                    # Les jetons ont pu être rafraîchis pendant la construction.
                    # Après l'arrêt, reprendre les derniers octets, sans rotation.
                    shutil.copy2(self.ancienne_racine/'.env',self.root/'.env')
                    secrets_actifs=self.ancienne_racine/'backend/secrets'
                    if secrets_actifs.exists():
                        shutil.copytree(secrets_actifs,self.root/'backend/secrets',dirs_exist_ok=True)
                    self.etat['secrets']=fichiers_secrets(self.root)
                    self.charger_config()
                print('Services applicatifs arrêtés ; sauvegarde cohérente des fichiers et de la base…')
                self.commande(['bash','backup.sh'])
                self.conserver_sessions()
                avant=self.donnees();(self.journal/'donnees-avant.json').write_text(json.dumps(avant,indent=2))
                self.migrations()
                apres=self.donnees(avant['colonnes']);(self.journal/'donnees-apres.json').write_text(json.dumps(apres,indent=2))
                if apres!=avant:raise Refus('Une donnée protégée a changé pendant les migrations. Application non basculée ; vérifier le journal et la sauvegarde.')
                if fichiers_secrets(self.root)!=self.etat['secrets']:raise Refus('Un fichier de secrets a changé pendant la livraison ; arrêt avant bascule.')
                ajout=preparer_secret_manquant(self.root,self.config)
                if ajout:print('Secret interne du navigateur ajouté ; aucune clé existante remplacée.')
                site=self.root/'backend/secrets/site_credentials.json'
                if not site.exists():
                    site.parent.mkdir(parents=True,exist_ok=True)
                    # Créer uniquement le fichier manquant, sans ouvrir/tronquer
                    # un fichier ajouté simultanément par l'exploitant.
                    try:
                        with site.open('x') as f:f.write('{}\n')
                    except FileExistsError:pass
                self.charger_config()
                self.bascule=True
                self.dc('up','-d','--no-build','--pull','never')
                self.dc('restart','nginx')
                import time
                for _ in range(40):
                    try:
                        r=json.loads(self.dc('exec','-T','backend','python','-c',"import urllib.request; print(urllib.request.urlopen('http://localhost:8000/api/ready',timeout=5).read().decode())"))
                        if r.get('pret') is True or r.get('ready') is True or r.get('status')=='ready':break
                    except (Refus,ValueError):pass
                    time.sleep(3)
                else:raise Refus('Le backend ne devient pas prêt après la bascule.')
                (self.journal/'termine.json').write_text(json.dumps({'readiness':r,'donnees_preservees':True,'secrets_existants_preserves':True},indent=2))
                print('Livraison terminée : données protégées identiques, clés conservées, backend prêt.')
                print('Journal privé : '+str(self.journal))
            except BaseException:
                # Les migrations restent additives. Pas de restauration du dump
                # sur la production : cela écraserait des écritures récentes.
                try:self.reprendre_anciens()
                except Exception:print('Reprise automatique incomplète : utiliser le journal privé de livraison.',file=sys.stderr)
                raise

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--appliquer',action='store_true');p.add_argument('--racine',default=str(Path(__file__).resolve().parents[1]));p.add_argument('--ancienne-racine');p.add_argument('--configuration-retour');args=p.parse_args()
    try:
        livraison=Livraison(args.racine,args.ancienne_racine,args.configuration_retour)
        livraison.appliquer() if args.appliquer else livraison.verifier()
        return 0
    except Refus as e:print('ARRÊT : '+str(e),file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())

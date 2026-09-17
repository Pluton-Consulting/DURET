#!/usr/bin/env python3
"""Installer une archive à côté du code actif, sans toucher aux volumes ni aux clés.

Le dossier courant actif vient des labels Docker. L'ancienne configuration
résolue est conservée en privé pour redémarrer aussi les anciens montages.
"""
import argparse,fcntl,hashlib,json,os,shutil,subprocess,sys,tarfile,tempfile,shlex
from pathlib import Path

def commande(args,cwd=None):
    r=subprocess.run(args,cwd=cwd,capture_output=True,text=True)
    if r.returncode:raise RuntimeError('Commande en échec : '+' '.join(args[:3])+'. Aucun secret affiché.')
    return r.stdout.strip()

def extraire(archive,cible):
    with tarfile.open(archive,'r:gz') as t:
        membres=t.getmembers()
        if len(membres)>30000 or sum(m.size for m in membres)>1024*1024*1024:raise ValueError('Archive trop volumineuse.')
        for m in membres:
            p=Path(m.name)
            if p.is_absolute() or '..' in p.parts or not(m.isfile() or m.isdir()):raise ValueError('Archive contenant un chemin ou un type interdit.')
            if any(c in ('.git','.env','node_modules','.livraisons','secrets') for c in p.parts):raise ValueError('Une archive de code ne doit contenir aucune configuration privée.')
        for m in membres:
            destination=cible/m.name
            if m.isdir():destination.mkdir(parents=True,exist_ok=True);continue
            destination.parent.mkdir(parents=True,exist_ok=True)
            with t.extractfile(m) as entree, destination.open('xb') as sortie:shutil.copyfileobj(entree,sortie)
            destination.chmod(0o755 if m.mode & 0o111 else 0o644)
    manifeste=json.loads((cible/'LIVRAISON.json').read_text())
    attendus=set(manifeste['sha256'])|{'LIVRAISON.json'}
    reels={str(p.relative_to(cible)) for p in cible.rglob('*') if p.is_file()}
    if reels!=attendus:raise ValueError('Contenu non couvert par le manifeste.')
    for nom,sha in manifeste['sha256'].items():
        chemin=Path(nom)
        if chemin.is_absolute() or '..' in chemin.parts:raise ValueError('Chemin du manifeste interdit.')
        p=cible/nom
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=sha:raise ValueError('Empreinte de livraison incorrecte : '+nom)
    return manifeste

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('archive');p.add_argument('--projet',required=True,choices=['duret-sols','symbiose-noa']);p.add_argument('--appliquer',action='store_true');args=p.parse_args()
    os.umask(0o077)
    # Deux archives ne doivent pas préparer deux bascules concurrentes.
    verrou_path=Path(tempfile.gettempdir())/('infra-ia-installation-'+hashlib.sha256(args.projet.encode()).hexdigest()+'.lock')
    verrou_fd=os.open(verrou_path,os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0),0o600)
    verrou=os.fdopen(verrou_fd,'a')
    try:fcntl.flock(verrou,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise ValueError('Une installation de ce projet est déjà en cours.')
    ids=commande(['docker','ps','-aq','--filter','label=com.docker.compose.project='+args.projet,'--filter','label=com.docker.compose.service=backend']).split()
    if len(ids)!=1:raise ValueError('Un seul backend existant est requis ; aucun projet créé automatiquement.')
    cont=json.loads(commande(['docker','inspect',ids[0]]))[0];labels=cont['Config']['Labels']
    ancienne=Path(labels['com.docker.compose.project.working_dir']).resolve()
    fichiers=labels.get('com.docker.compose.project.config_files','').split(',')
    if not fichiers or any(not Path(f).is_file() for f in fichiers):raise ValueError('Configuration active introuvable ; aucune mutation de production.')
    noms_compose=[Path(f).name for f in fichiers]
    if noms_compose not in (['docker-compose.yml','docker-compose.prod.yml'],['docker-compose.yml','docker-compose.prod.yml','docker-compose.https.yml']):
        raise ValueError('La configuration active comporte des overlays spécifiques. Livraison arrêtée avant toute modification ; conserver et adapter ces overlays avant de relancer.')
    dc=['docker','compose','-p',args.projet]
    for f in fichiers:dc+=['-f',f]
    config=json.loads(commande(dc+['config','--format','json'],ancienne))
    for nom in config['services']:
        service_ids=commande(['docker','ps','-aq','--filter','label=com.docker.compose.project='+args.projet,'--filter','label=com.docker.compose.service='+nom]).split()
        if len(service_ids)>1:raise ValueError('Plusieurs conteneurs pour '+nom+' ; retour arrière ambigu.')
        if service_ids:
            info=json.loads(commande(['docker','inspect',service_ids[0]]))[0]
            try:commande(['docker','image','inspect',info['Image']])
            except RuntimeError:raise ValueError('Image précédente de '+nom+' introuvable : restaurer son archive Docker avant de relancer. Aucun service arrêté.')
            reference=info['Image']
            if args.appliquer:
                # Un identifiant seul peut disparaître quand le tag de build est
                # remplacé. Garder une référence nommée avant toute construction.
                reference='infra-ia-retour/'+args.projet+'/'+nom+':'+info['Image'].split(':')[-1][:32]
                commande(['docker','image','tag',info['Image'],reference])
            config['services'][nom]['image']=reference
    releases=ancienne.parent if ancienne.parent.name=='.livraisons-code-'+args.projet else ancienne.parent/('.livraisons-code-'+args.projet);releases.mkdir(mode=0o700,exist_ok=True)
    nouvelle=Path(tempfile.mkdtemp(prefix='version-',dir=releases))
    manifeste=extraire(Path(args.archive).resolve(),nouvelle)
    if manifeste.get('projet')!=args.projet:raise ValueError('Cette archive appartient à un autre projet.')
    # L'overlay HTTPS est accepté seulement si sa définition et Caddy sont identiques.
    if 'docker-compose.https.yml' in noms_compose:
        for nom in ('docker-compose.https.yml','caddy/Caddyfile','caddy/Dockerfile'):
            if (ancienne/nom).read_bytes()!=(nouvelle/nom).read_bytes():
                raise ValueError('Configuration HTTPS spécifique à conserver : '+nom)
    (nouvelle/'.livraison-compose.json').write_text(json.dumps(noms_compose))
    shutil.copy2(ancienne/'.env',nouvelle/'.env')
    if (ancienne/'backend/secrets').exists():shutil.copytree(ancienne/'backend/secrets',nouvelle/'backend/secrets',dirs_exist_ok=True)
    retour=nouvelle/'.configuration-retour.json';retour.write_text(json.dumps(config))
    commande_retour=['docker','compose','-p',args.projet,'--project-directory',str(ancienne),'-f',str(retour),'up','-d','--no-build','--pull','never']
    (nouvelle/'RETOUR-ARRIERE.txt').write_text('Ancien dossier : '+str(ancienne)+'\nConfiguration privée : '+str(retour)+'\nCommande : '+shlex.join(commande_retour)+'\nPuis : '+shlex.join(commande_retour[:8]+['restart','nginx'])+'\n')
    livraison=[sys.executable,str(nouvelle/'scripts/livrer.py'),'--racine',str(nouvelle),'--ancienne-racine',str(ancienne),'--configuration-retour',str(retour)]
    with (nouvelle/'RETOUR-ARRIERE.txt').open('a') as f:f.write('Réappliquer cette livraison après retour : '+shlex.join(livraison+['--appliquer'])+'\n')
    if args.appliquer:livraison.append('--appliquer')
    print('Code préparé dans : '+str(nouvelle),flush=True)
    # Lancer en héritant du terminal : progrès visibles, aucune sortie contenant
    # la configuration résolue ou les valeurs de clés.
    resultat=subprocess.run(livraison,cwd=nouvelle).returncode
    if resultat==0 and args.appliquer:
        # Conserver les entrées déjà utilisées par le cron, avec découverte du
        # dossier actif. Aucun contenu métier ni clé de l’ancien checkout changé.
        sauvegarde=ancienne/'.operations-avant-livraison';sauvegarde.mkdir(mode=0o700,exist_ok=True)
        operations=['backup.sh','restaurer.sh','scripts/verrou_backup.py','scripts/livrer.py','.livraison-compose.json']
        if (nouvelle/'scripts/compose_livraison.py').is_file():operations.append('scripts/compose_livraison.py')
        for nom in operations:
            avant=ancienne/nom
            avant.parent.mkdir(parents=True,exist_ok=True)
            (sauvegarde/nom).parent.mkdir(parents=True,exist_ok=True)
            if avant.is_file() and not (sauvegarde/nom).exists():shutil.copy2(avant,sauvegarde/nom)
            shutil.copy2(nouvelle/nom,avant)
        print('Les anciennes commandes de sauvegarde/restauration suivent maintenant le dossier actif.',flush=True)
    verrou.close()
    return resultat
if __name__=='__main__':
    try:sys.exit(main())
    except Exception as e:print('ARRÊT : '+str(e),file=sys.stderr);sys.exit(1)

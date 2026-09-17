"""L'archive exclut les secrets ; le précontrôle ne modifie pas le code actif."""
import io,json,hashlib,tarfile,tempfile,importlib.util,sys,types
from pathlib import Path
from unittest.mock import patch
R=Path(sys.argv[1]).resolve().parent
sp=importlib.util.spec_from_file_location('installateur',R/'scripts/installer-livraison.py');m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m)
b=Path(tempfile.mkdtemp(prefix='installateur-test-'));releases=b/'.livraisons-code-duret-sols';ancien=releases/'version-initiale';ancien.mkdir(parents=True)
for n in ('docker-compose.yml','docker-compose.prod.yml','backup.sh','restaurer.sh'):(ancien/n).write_text('ancien')
(ancien/'.env').write_text('CLE=fictive\n');(ancien/'backend/secrets').mkdir(parents=True);(ancien/'backend/secrets/token.json').write_text('{"token":"fictif"}')
def archive(nom,fichiers,extra=None):
 p=b/nom;mani={'projet':'duret-sols','sha256':{n:hashlib.sha256(v).hexdigest() for n,v in fichiers.items()}}
 with tarfile.open(p,'w:gz') as t:
  for n,v in {**fichiers,'LIVRAISON.json':json.dumps(mani).encode(),**(extra or {})}.items():
   i=tarfile.TarInfo(n);i.size=len(v);t.addfile(i,io.BytesIO(v))
 return p
ok=archive('ok.tar.gz',{'scripts/livrer.py':b'# faux','scripts/verrou_backup.py':b'# verrou fictif','backup.sh':b'nouveau','restaurer.sh':b'nouveau'})
for p in (archive('secret.tar.gz',{'.env':b'interdit'}),archive('extra.tar.gz',{'script':b'code'},extra={'inconnu':b'extra'})):
 cible=b/(p.stem+'-extrait');cible.mkdir()
 try:m.extraire(p,cible);raise AssertionError('Archive invalide acceptée')
 except ValueError:pass
labels={'com.docker.compose.project.working_dir':str(ancien),'com.docker.compose.project.config_files':','.join(str(ancien/n) for n in ('docker-compose.yml','docker-compose.prod.yml'))}
etiquettes=[]
def commande(args,cwd=None):
 if args[:3]==['docker','image','tag']:etiquettes.append(args);return ''
 if args[:3]==['docker','image','inspect']:return '[]'
 if args[:2]==['docker','ps']:return 'backend'
 if args[:2]==['docker','inspect']:return json.dumps([{'Config':{'Labels':labels},'Image':'sha256:ancienne-image'}])
 if args[-3:]==['config','--format','json']:return json.dumps({'services':{'backend':{}},'name':'duret-sols'})
 raise AssertionError(args)
with patch.object(m.tempfile,'gettempdir',return_value=str(b)),patch.object(m,'commande',commande),patch.object(m.subprocess,'run',return_value=types.SimpleNamespace(returncode=0)):
 for appliquer in (False,True):
  with patch.object(sys,'argv',['installer',str(ok),'--projet','duret-sols']+(['--appliquer'] if appliquer else [])):assert m.main()==0
  assert (ancien/'backup.sh').read_text()==('nouveau' if appliquer else 'ancien')
  assert bool(etiquettes)==appliquer
assert (ancien/'scripts/verrou_backup.py').is_file()
assert (ancien/'scripts/livrer.py').is_file()
for rep in releases.glob('version-*'):
 if (rep/'RETOUR-ARRIERE.txt').exists():
  retour=(rep/'RETOUR-ARRIERE.txt').read_text(); assert '--project-directory' in retour and 'Réappliquer cette livraison' in retour
assert not (releases/'.livraisons-code-duret-sols').exists()
assert (ancien/'.env').read_text()=='CLE=fictive\n'
assert (ancien/'.operations-avant-livraison/backup.sh').read_text()=='ancien'
print('✓ Archive privée/incomplète refusée ; précontrôle sans modification du code actif ; anciens scripts conservés ; versions sans imbrication')

# Topologie réellement employée sur le VPS : HTTPS et ses fichiers inchangés.
for n in ('docker-compose.https.yml','caddy/Caddyfile','caddy/Dockerfile'):
 (ancien/n).parent.mkdir(parents=True,exist_ok=True);(ancien/n).write_text('https conserve')
labels['com.docker.compose.project.config_files']+=','+str(ancien/'docker-compose.https.yml')
https=archive('https.tar.gz',{'scripts/livrer.py':b'# faux',**{n:b'https conserve' for n in ('docker-compose.https.yml','caddy/Caddyfile','caddy/Dockerfile')}})
with patch.object(m.tempfile,'gettempdir',return_value=str(b)),patch.object(m,'commande',commande),patch.object(m.subprocess,'run',return_value=types.SimpleNamespace(returncode=0)),patch.object(sys,'argv',['installer',str(https),'--projet','duret-sols']):
 assert m.main()==0
 (ancien/'caddy/Caddyfile').write_text('reglage propre au VPS')
 try:m.main();raise AssertionError('Configuration HTTPS differente acceptee')
 except ValueError as e:assert 'HTTPS' in str(e)
print('✓ HTTPS standard conserve ; personnalisation Caddy refusee sans bascule')

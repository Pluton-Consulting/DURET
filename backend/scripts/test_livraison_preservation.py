"""Exerce la livraison : pas de volume neuf, pas de clé remplacée, retour arrière."""
import importlib.util,json,tempfile,sys,types,copy
from pathlib import Path
from unittest.mock import patch
B=Path(sys.argv[1]).resolve();R=B.parent
spec=importlib.util.spec_from_file_location('livrer',R/'scripts/livrer.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def fixture():
 r=Path(tempfile.mkdtemp(prefix='livraison-simulee-'));(r/'backend/secrets').mkdir(parents=True)
 (r/'.env').write_bytes(b'# conserve exactement\nPOSTGRES_PASSWORD=fictif\nJWT_SECRET_KEY=fictif-jwt\n')
 (r/'backend/secrets/token.json').write_bytes(b'{"token":"fictif-conserve"}')
 return r

class FausseLivraison(m.Livraison):
 def __init__(self,root,defaut=''):
  super().__init__(root);self.appels=[];self.defaut=defaut;self.migre=False
  self.conf={'name':'existant-'+root.name,'volumes':{'pg':{'name':'pg-existant'},'docs':{'name':'docs-existants'}},'services':{
   'postgres':{'environment':{'POSTGRES_USER':'admin','POSTGRES_DB':'metier','POSTGRES_PASSWORD':'fictif'},'volumes':[{'type':'volume','source':'pg','target':'/var/lib/postgresql/data'}]},
   'backend':{'environment':{'DATABASE_URL':'postgresql://admin:fictif@postgres/metier','JWT_SECRET_KEY':'fictif-jwt'},'volumes':[{'type':'volume','source':'docs','target':'/documents'}]}}}
 def commande(self,args,entree=None):
  self.appels.append(args)
  if args[:2]==['git','rev-parse']:return 'revision-fictive'
  if args[:2]==['docker','ps'] or args[:3]==['docker','image','tag']:return ''
  if args[:2]==['docker','inspect']:
   n=args[2];montages=([{'Destination':'/var/lib/postgresql/data','Type':'volume','Name':'autre' if self.defaut=='volume' else 'pg-existant'}] if n=='postgres' else [{'Destination':'/documents','Type':'volume','Name':'docs-existants'}])
   return json.dumps([{'Id':n,'Image':'sha256:ancienne-'+n,'State':{'Running':True},'Mounts':montages,'Config':{'Env':['JWT_SECRET_KEY='+('change' if self.defaut=='cle' else 'fictif-jwt')]}}])
  if args[:3]==['docker','volume','inspect'] or args[:2]==['docker','start']:return ''
  if args==['bash','backup.sh']:
   if self.defaut=='sauvegarde':raise m.Refus('Sauvegarde simulée en échec')
   return ''
  if args[:2]==['docker','compose']:
   if args[-3:]==['config','--format','json']:return json.dumps(self.conf)
   if 'ps' in args:return args[-1]
   if 'psql' in args:return '1'
   if 'python' in args:
    if self.defaut=='readiness':raise m.Refus('pas prêt')
    return '{"pret":true}'
   return ''
  raise AssertionError(args)
 def donnees(self,colonnes=None):
  return {'colonnes':{'users':['id','email']},'tables':{'users':{'lignes':2,'empreinte':'change' if self.migre and self.defaut=='donnees' else 'identique'}}}
 def migrations(self):self.appels.append(['migrations']);self.migre=True

for defaut in ('volume','cle'):
 r=fixture();a=FausseLivraison(r,defaut)
 try:a.appliquer()
 except m.Refus:pass
 else:raise AssertionError('Précontrôle permissif '+defaut)
 assert not any('build' in x for x in a.appels)
 print('✓ Refus avant mutation :',defaut)
for defaut in ('sauvegarde','donnees','readiness',''):
 r=fixture();avant=(r/'.env').read_bytes();cle=(r/'backend/secrets/token.json').read_bytes();a=FausseLivraison(r,defaut)
 with patch('time.sleep',lambda _:None):
  try:a.appliquer()
  except m.Refus:assert defaut
  else:assert not defaut
 assert (r/'.env').read_bytes().startswith(avant)
 assert (r/'backend/secrets/token.json').read_bytes()==cle
 if defaut in ('sauvegarde','donnees'):
  assert not any('up' in x for x in a.appels)
  assert ['docker','start','backend'] in a.appels
 elif defaut=='readiness':
  assert any('images-precedentes.json' in ' '.join(x) and '--no-build' in x for x in a.appels)
 else:
  assert (r/'backend/secrets/site_credentials.json').read_text()=='{}\n'
  assert len(list((r/'.livraisons').glob('*/termine.json')))==1
  appels=[' '.join(x) for x in a.appels];assert next(i for i,x in enumerate(appels) if x.startswith('docker image tag')) < next(i for i,x in enumerate(appels) if ' build' in x)
  assert next(i for i,x in enumerate(appels) if 'stop' in x)<appels.index('bash backup.sh')<appels.index('migrations')
 print('✓ Scénario',defaut or 'réussite',': clés conservées, étapes et reprise conformes')
print('✓ 0 échec')

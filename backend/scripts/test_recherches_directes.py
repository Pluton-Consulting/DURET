import sys,ast,asyncio,types,tempfile,os,json
from pathlib import Path
B=Path(sys.argv[1]).resolve();sys.path.insert(0,str(B));os.environ['DOCUMENTS_DIR']=tempfile.mkdtemp(prefix='recherche-test-')
from skills.recherche_sources import fichiers
assert fichiers({'bloc_ui':{'rows':[['devis.docx','Fichier','Clients/A']]}})[0]['chemin']=='Clients/A/devis.docx'
assert fichiers({'resultats':[{'nom':'devis.docx','chemin':'/Clients/A/devis.docx'}]})[0]['chemin']=='/Clients/A/devis.docx'
if (B/'outils/drive.py').exists():
 tree=ast.parse((B/'outils/drive.py').read_text());n=next(x for x in tree.body if isinstance(x,ast.AsyncFunctionDef) and x.name=='_chercher_fichiers_pages');ns={'asyncio':asyncio};exec(compile(ast.Module(body=[n],type_ignores=[]),'drive','exec'),ns)
 class Api:
  def __init__(self):self.appels=[];self.limite=False
  def files(self):return self
  def list(self,**kw):self.appels.append(kw);return self
  def execute(self):
   if self.limite:return {'files':[{'id':'x'}],'nextPageToken':'identique'}
   return {'files':[{'id':'page1'}],'nextPageToken':'suite'} if 'pageToken' not in self.appels[-1] else {'files':[{'id':'page2'}]}
 async def test():
  a=Api();f,p=await ns['_chercher_fichiers_pages'](a,"'racine' in parents and fullText contains 'devis'");assert len(f)==2 and not p and a.appels[1]['pageToken']=='suite'
  assert all("'racine' in parents" in x['q'] for x in a.appels)
  a=Api();a.limite=True;f,p=await ns['_chercher_fichiers_pages'](a,'filtre');assert p and len(a.appels)==2
 asyncio.run(test());print('✓ Drive : pages fournisseur suivies, périmètre conservé, jeton répété signalé')
else:
 from contextlib import asynccontextmanager
 import skills.recherche_nas_contenu as scan
 acces=types.ModuleType('nas.acces');acces.verifier_role=lambda u:None;acces.verifier=lambda p:p
 @asynccontextmanager
 async def connexion():yield None,None,None
 async def lister(c,b,s,p,tout=False):
  return {'entrees':[{'chemin':'/Clients/A/f'+str(i)+'.txt','nom':'f'+str(i)+'.txt','dossier':False} for i in range(25)]}
 lus=[]
 async def lire(c,b,s,p,uid):lus.append(p);return {'texte':'Prestation terrasse pour le client A'}
 acces.connexion=connexion;acces._lister_ouvert=lister;acces._lire_ouvert=lire;sys.modules['nas.acces']=acces
 async def test():
  user=types.SimpleNamespace(id='A');r=await scan.chercher({'dossier':'/Clients/A','motif':'terrasse'},user);assert r['reprise'] and len(lus)==19
  try:await scan.chercher({'reprise':r['reprise']},types.SimpleNamespace(id='B'));raise AssertionError('Autre utilisateur accepté')
  except ValueError:pass
  r=await scan.chercher({'reprise':r['reprise']},user);assert r['termine'] and len(lus)==25 and len(set(lus))==25 and r['fichiers_lus']==25
 asyncio.run(test());print('✓ NAS : 25 fichiers sur deux lots, reprise conservée, aucune double lecture, autre utilisateur refusé')

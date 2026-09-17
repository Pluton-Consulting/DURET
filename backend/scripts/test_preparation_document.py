"""Référence du fil et trames réelles prioritaires ; secours avec la bonne identité."""
import asyncio,sys,types,tempfile,os
from pathlib import Path
B=Path(sys.argv[1]).resolve();sys.path.insert(0,str(B));os.environ['DOCUMENTS_DIR']=tempfile.mkdtemp(prefix='modele-doc-test-')
lignes=[];appels=[]
class C:
 async def fetch(self,sql,*args):assert 'genre=\'document\'' in sql and args;return list(lignes)
class DB:
 async def __aenter__(self):return C()
 async def __aexit__(self,*a):return False
sys.modules['database.connection']=types.SimpleNamespace(get_db=lambda:DB())
from skills.preparation_document import preparer
from skills.trames import noter_travail
async def executer(nom,args,**kw):appels.append((nom,kw['user'].id));return {'ok':True,'output':{'resultats':[{'nom':'Modèle devis.docx'}]}}
sys.modules['skills.executor']=types.SimpleNamespace(execute_skill=executer)
async def test():
 user=types.SimpleNamespace(id='A')
 lignes.append({'nom':'Devis de la maison','genre':'document','description':'Modèle devis','type_fichier':'docx'})
 r=await preparer({'demande':'Devis','_fil':'fil'},user);assert r['trames_candidates'] and not appels
 lignes.clear();noter_travail(user,'fil',reference='document choisi')
 r=await preparer({'demande':'Devis','_fil':'fil'},user);assert r['reference_du_fil']['reference']=='document choisi' and not appels
 r=await preparer({'demande':'Devis','_fil':'autre'},user);assert appels==[('rechercher_documents','A')] and not r['exhaustive']
asyncio.run(test());print('✓ Référence de la conversation, trames réelles, recherche autorisée de secours et couverture partielle')

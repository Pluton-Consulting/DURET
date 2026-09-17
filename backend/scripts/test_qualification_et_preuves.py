"""Pas de promotion sans preuve ; chiffres ancrés dans le texte et les droits."""
import asyncio,sys,types,tempfile,os
from pathlib import Path
B=Path(sys.argv[1]).resolve();sys.path.insert(0,str(B));os.environ['DOCUMENTS_DIR']=tempfile.mkdtemp(prefix='preuve-test-')
from learning.qualification import verifier_code,verifier_cas,evaluer
code='def run(data):\n    return {"total": data.get("a", 0) + data.get("b", 0)}'
assert len(verifier_code(code))==64
for mauvais in ('def run(data):\n return open("/etc/passwd").read()', 'import os\ndef run(data):\n return {}', 'def run(data):\n return data.__class__'):
 try:verifier_code(mauvais);raise AssertionError('Code système accepté')
 except ValueError:pass
cas=[{'data':{},'attendu':{'total':0}},{'data':{'a':1},'attendu':{'total':1}},{'data':{'a':-2,'b':2},'attendu':{'total':0}}]
try:verifier_cas([cas[0]]*3);raise AssertionError('Cas identiques acceptés')
except ValueError:pass
class Sandbox:
 def __init__(self):self.isole=True;self.calls=[];self.faux=False
 def isolement(self):return 'daytona' if self.isole else 'subprocess'
 async def execute_skill(self,code,nom,data,**kw):
  self.calls.append(data);return {'ok':True,'output':{'total':999 if self.faux else data.get('a',0)+data.get('b',0)},'sandbox_type':'daytona'}
s=Sandbox();m=types.ModuleType('sandbox.daytona_client');m.sandbox_client=s;sys.modules['sandbox.daytona_client']=m
async def qualif():
 assert (await evaluer('s',code,cas))['passed'] and len(s.calls)==3
 s.faux=True;assert not (await evaluer('s',code,cas))['passed']
 s.isole=False;s.calls=[];assert not (await evaluer('s',code,cas))['passed'] and not s.calls
asyncio.run(qualif())
from skills import chiffres_sources as chiffres
source={'type':'nas','args':{'chemin':'Chantier/Devis.txt'}};texte='Surface terrasse : 85 m²\nPrix unitaire : 85,00 EUR\nAncien total : 7 225,00 €'
r=chiffres.extraire(texte,source,'A');assert [x['valeur'] for x in r['chiffres']]==['85','85.00','7225.00']
assert chiffres.calculer('c1*c2',{'c1':'85','c2':'85.00'})=='7225.00'
assert chiffres.calculer('c1+c2',{'c1':'0.1','c2':'0.2'})=='0.3'
for expr in ('__import__("os")','c1+999','c1**100000'):
 try:chiffres.calculer(expr,{'c1':'1'});raise AssertionError('Expression acceptée')
 except (ValueError,SyntaxError):pass
async def lire(source,user):return texte
chiffres.lecture=lire
async def calcul():
 d={'references':[x['ref'] for x in r['chiffres'][:2]],'expression':'c1*c2'}
 assert (await chiffres.calcul(d,types.SimpleNamespace(id='A')))['resultat_decimal']=='7225.00'
 try:await chiffres.calcul(d,types.SimpleNamespace(id='B'));raise AssertionError('Autre utilisateur accepté')
 except ValueError:pass
 async def change(source,user):return texte+'\nNouvelle version'
 chiffres.lecture=change
 try:await chiffres.calcul(d,types.SimpleNamespace(id='A'));raise AssertionError('Source changée acceptée')
 except ValueError:pass
asyncio.run(calcul())
print('✓ Qualification : entrées distinctes, échec détecté, aucun repli local ; chiffres cités, décimaux exacts, source changée et autre utilisateur refusés')

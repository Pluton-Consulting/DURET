"""Même jour, lots MIME bornés, compte et lecture seule ; aucun fournisseur réel."""
import sys,os
os.environ.setdefault("DATABASE_URL","postgresql://test:test@127.0.0.1/test")
os.environ.setdefault("JWT_SECRET_KEY","fictif-test-pagination-uniquement-1234567890")
os.environ.setdefault("RESEND_API_KEY","fictif")
from pathlib import Path
sys.path.insert(0,str(Path(sys.argv[1] if len(sys.argv)>1 else 'backend').resolve()))
from unittest.mock import patch
from email.message import EmailMessage
from mail import imap
m=EmailMessage();m['From']='test@example.test';m['To']='client@example.test';m['Date']='Wed, 16 Sep 2026 12:00:00 +0200';m['Subject']='Vérification';m.set_content('Merci de confirmer la date du chantier.');m.add_attachment(b'A'*150000,maintype='application',subtype='pdf',filename='piece.pdf')
brut=m.as_bytes()
class Client:
 def __init__(self):self.calls=[]
 def response(self,k):return k,[b'42']
 def uid(self,cmd,*args):
  self.calls.append((cmd,args))
  if cmd=='search':return 'OK',[b'1 2 3 4 5 6 7 8 9 10']
  assert cmd=='fetch' and 'BODY.PEEK[]<0.65536>' in args[1]
  return 'OK',[(f'{u.decode()} (UID {u.decode()} FLAGS () RFC822.SIZE {len(brut)} BODY[]<0> {{65536}}'.encode(),brut[:65536]) for u in args[0].split(b',')]
 def select(self,*args,**kwargs):
  assert kwargs.get("readonly") is True
  return "OK",[]
 def logout(self):pass
c=Client()
with patch.object(imap,'_connexion',lambda:c),patch.object(imap,'_selectionner',lambda c,d:None,create=True),patch('mail.lecture._memoriser',lambda uid,b:uid):
 p1,total=imap.lister('test@example.test','INBOX',5)
 p2,restant=imap.lister('test@example.test','INBOX',5,curseur=p1[-1]['curseur_suivant'])
 assert total==10 and restant==5
 assert {m['ref'] for m in p1+p2}=={'INBOX|'+str(i) for i in range(1,11)}
 assert all('confirmer' in m['apercu'] and not m['lecture_integrale'] for m in p1+p2)
 assert len([x for x in c.calls if x[0]=='fetch'])==2
 try:imap.lister('test@example.test','INBOX',5,curseur='imap:41:6');raise AssertionError('validité périmée acceptée')
 except ValueError:pass
print('OK : 10 messages du même jour, aucun saut/doublon, 2 lectures groupées bornées, UIDVALIDITY vérifiée.')
# Le point périodique parcourt toutes les pages sans demander au modèle de
# choisir la suivante, ni inventer une date qui saute le reste de la journée.
import ast,asyncio,re,types
source=Path(sys.argv[1] if len(sys.argv)>1 else 'backend')/'skills/routines.py'
n=next(n for n in ast.parse(source.read_text()).body if isinstance(n,ast.AsyncFunctionDef) and n.name=='check_mails')
espace={'re':re};exec(compile(ast.Module(body=[n],type_ignores=[]),str(source),'exec'),espace)
appels=[]
async def lire(data,user):
 appels.append(data);debut={None:0,'imap:42:6':5}[data.get('curseur')]
 return {'messages':[{'ref':str(i),'de':'test@example.test','objet':'Question','date_iso':'2026-09-16','apercu':'Merci de confirmer la date.','lu':False} for i in range(debut,debut+5)],'total_periode':10-debut,'tronque':debut==0,'curseur_suivant':'imap:42:6' if debut==0 else None,'plus_ancien':'2026-09-16','boite':'test@example.test'}
async def tester():
 module=types.ModuleType('mail.skills');module.lire_mails=lire
 with patch.dict(sys.modules,{'mail.skills':module}):
  r=await espace['check_mails']({'depuis':'7j'},types.SimpleNamespace(id='test'))
 assert r['nombre']==r['total_periode']==10 and not r['tronque'] and r['pour_continuer'] is None
 assert len(appels)==2 and appels[1]['curseur']=='imap:42:6' and not appels[1].get('avant')
 assert len({m['ref'] for m in r['messages']})==10
asyncio.run(tester())
print('OK : synthèse périodique avec couverture entière et pagination mécanique.')

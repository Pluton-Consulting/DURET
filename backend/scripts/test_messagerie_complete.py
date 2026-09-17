"""Contrats de mutation réels avec fournisseurs simulés, aucun réseau."""
import sys,types,asyncio,base64
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from email.message import EmailMessage
from email.parser import BytesParser
from email import policy
from skills.brouillons_distants import retoucher_mime,_gmail,_imap,charge
from skills import gestion_mail as g
m=EmailMessage();m['To']='ancien@example.test';m['Subject']='Avant';m['In-Reply-To']='<fil@example.test>';m.set_content('Ancien texte');m.add_alternative('<b>Ancien</b>',subtype='html');m.add_attachment(b'PHOTO',maintype='image',subtype='png',filename='photo.png');m.add_attachment(b'TEXTE PIECE',maintype='text',subtype='plain',filename='source.txt')
n=BytesParser(policy=policy.default).parsebytes(retoucher_mime(m.as_bytes(),{'corps':'Nouveau <texte>','objet':'Après'},[{'nom':'devis.pdf','mime':'application/pdf','octets':b'PDF'}]))
assert n['Subject']=='Après' and n['In-Reply-To']==m['In-Reply-To']
assert 'Nouveau <texte>' in n.get_body(preferencelist=('plain',)).get_content()
assert '&lt;texte&gt;' in n.get_body(preferencelist=('html',)).get_content()
assert [(p.get_filename(),p.get_payload(decode=True)) for p in n.iter_attachments()]==[('photo.png',b'PHOTO'),('source.txt',b'TEXTE PIECE'),('devis.pdf',b'PDF')]
for v in ({'lu':'false'},{'ajouter_categories':['A'],'retirer_categories':['A']},{'suivi':'inconnu'}):
 try:g.changements(v);raise AssertionError('accepté')
 except ValueError:pass
class Req:
 def __init__(self,r):self.r=r
 def execute(self):return self.r
class Gmail:
 def __init__(self):self.raw=base64.urlsafe_b64encode(m.as_bytes()).decode();self.labels_={'UNREAD'};self.writes=[]
 def users(self):return self
 def drafts(self):return self
 def messages(self):return self
 def get(self,**kw):return Req({'id':'d1','message':{'raw':self.raw,'threadId':'fil'}} if kw.get('format')=='raw' else {'id':'m1','labelIds':list(self.labels_)})
 def update(self,**kw):self.writes.append(kw);self.raw=kw['body']['message']['raw'];return Req({'id':'d1'})
 def modify(self,**kw):self.labels_|=set(kw['body']['addLabelIds']);self.labels_-=set(kw['body']['removeLabelIds']);return Req({})
s=Gmail();g._service_gmail=lambda *a:s
r=_gmail('a@example.test','d1',{'objet':'Final'},[]);assert r['id_brouillon']=='d1' and len(s.writes)==1 and s.writes[0]['body']['message']['threadId']=='fil'
r=g._gmail_modifier('a@example.test','m1',g.changements({'lu':True,'suivi':'actif'}));assert r['labels']==['STARRED']
# Les faux modules n'enlèvent que la connexion ; le contrôle métier est réel.
imap=types.ModuleType('mail.imap');lecture=types.ModuleType('mail.lecture');lecture._controler_identifiant=lambda ident,a:None
imap.utf7_encoder=lambda x:x
class Imap:
 capabilities=(b'IMAP4REV1',b'UIDPLUS')
 def __init__(self):self.calls=[]
 def select(self,*a,**k):return 'OK',[]
 def uid(self,*a):
  self.calls.append(a)
  if a[0]=='FETCH':return 'OK',[(b'1 (FLAGS (\\Draft) BODY[]',m.as_bytes())]
  return 'OK',[]
 def append(self,*a):self.calls.append(('APPEND',));return 'OK',[b'[APPENDUID 7 99] Done']
 def response(self,nom):return 'UIDVALIDITY',[b'7']
 def logout(self):pass
c=Imap();imap._connexion=lambda:c;sys.modules['mail.imap']=imap;sys.modules['mail.lecture']=lecture
import mail
mail.imap=imap
r=_imap('Drafts|12',{'objet':'Version'},[],None);assert r['id_brouillon']=='Drafts|99' and ('EXPUNGE','12') in c.calls and not any(x[0]=='EXPUNGE' and len(x)<2 for x in c.calls)
c.calls=[]
try:_imap('Drafts|12',{'objet':'Version'},[],None,'8');raise AssertionError('Ancienne validité acceptée')
except ValueError:pass
assert not c.calls
c.capabilities=(b'IMAP4REV1',);c.calls=[]
try:_imap('Drafts|12',{'objet':'Version'},[],None);raise AssertionError('UIDPLUS absent accepté')
except ValueError:pass
assert not c.calls
print('✓ MIME, pièces, fil, brouillon stable Gmail, indicateurs relus et remplacement IMAP ciblé')

# Contrat HTTP Outlook : version conditionnelle, petites pièces et relecture.
import httpx
from unittest.mock import patch
from skills.brouillons_distants import _outlook
async def jeton():return 'jeton-fictif'
sys.modules['ingestion.connectors.outlook']=types.SimpleNamespace(_jeton=jeton)
class Reponse:
 def __init__(self,v):self.v=v
 def json(self):return self.v
 def raise_for_status(self):pass
class Graph:
 def __init__(self):self.message={'id':'draft1','isDraft':True,'subject':'Avant','isRead':False,'categories':['Ancienne'],'flag':{'flagStatus':'notFlagged'},'@odata.etag':'version-1'};self.calls=[]
 async def __aenter__(self):return self
 async def __aexit__(self,*a):return False
 async def get(self,url,**kw):self.calls.append(('GET',url,kw));return Reponse(dict(self.message))
 async def patch(self,url,**kw):self.calls.append(('PATCH',url,kw));assert kw['headers']['If-Match']=='version-1';self.message.update(kw['json']);return Reponse(dict(self.message))
 async def post(self,url,**kw):self.calls.append(('POST',url,kw));return Reponse({'id':'piece1'})
async def outlook():
 graph=Graph()
 with patch.object(httpx,'AsyncClient',lambda **kw:graph):
  r=await _outlook('boite@example.test','draft1',{'objet':'Après','corps':'Texte'},[{'nom':'photo.png','mime':'image/png','octets':b'PHOTO','inline':True,'cid':'photo'}])
  assert r['id_brouillon']=='draft1'
  posts=[a for a in graph.calls if a[0]=='POST'];assert len(posts)==1 and posts[0][1].endswith('/draft1/attachments')
  assert base64.b64decode(posts[0][2]['json']['contentBytes'])==b'PHOTO'
  r=await g._outlook_modifier('boite@example.test','draft1',g.changements({'lu':True,'suivi':'actif','ajouter_categories':['Nouvelle']}))
  assert r['observe']['isRead'] is True and r['observe']['categories']==['Ancienne','Nouvelle']
asyncio.run(outlook())
print('✓ Outlook : écriture conditionnelle, brouillon conservé, image jointe via la bonne route, indicateurs relus')

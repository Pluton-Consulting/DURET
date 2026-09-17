"""Le nom exact du NAS prime, sans contourner les racines ni les droits."""
import os,sys,asyncio
from pathlib import Path
sys.path.insert(0,str(Path(sys.argv[1] if len(sys.argv)>1 else 'backend').resolve()))
os.environ.setdefault('DATABASE_URL','postgresql://test:test@localhost/test')
os.environ.setdefault('JWT_SECRET_KEY','cle-fictive-tests-nas-uniquement-123456789012345')
os.environ.setdefault('RESEND_API_KEY','fictif')
from unittest.mock import patch,AsyncMock
from nas import acces,niveaux
from security import lecteur
from ingestion.connectors import synology
async def main():
 with patch.object(acces,'dossiers_autorises',return_value=['/racine']),patch.object(niveaux,'visible_pour',return_value=True),patch.object(niveaux,'filtrer',side_effect=lambda e,r:e):
  for total in [3,0]:
   entries=[{'path':'/racine/'+n,'name':n,'isdir':False} for n in ['a.pdf','~$cadre.docx','.DS_Store']]
   with patch.object(synology,'_appel',AsyncMock(return_value={'total':total,'files':entries})):
    r=await acces._lister_ouvert(None,'','', '/racine');assert r['total']==1 and not r['tronque'] and r['entrees'][0]['nom']=='a.pdf',r
  exact='/racine/r%C3%A9emploi.zip';decoded='/racine/réemploi.zip';vus=[]
  async def taille(c,b,s,p):
   vus.append(p);return (100_000_000,'') if p==exact else (0,'introuvable')
  with patch.object(acces,'_taille_ouverte',side_effect=taille),patch.object(synology,'_telecharger_ou_raison',AsyncMock(side_effect=AssertionError('téléchargement interdit'))) as dl:
   r=await acces._lire_ouvert(None,'','',exact);assert r['chemin']==exact and r['octets']==100_000_000;assert vus==[decoded,exact];dl.assert_not_called()
  for interdit in ['/racine/%2e%2e/prive/x.pdf','/autre/x.pdf','/']:
   try:acces.verifier(interdit)
   except acces.NasRefuse:pass
   else:raise AssertionError('confinement contourné')
  with patch.object(niveaux,'visible_pour',return_value=False):
   try:acces.verifier(exact)
   except acces.NasRefuse:pass
   else:raise AssertionError('droits contournés')
 from contextlib import asynccontextmanager
 from outils import nas as outil
 @asynccontextmanager
 async def connexion():yield None,'',''
 lecture=AsyncMock(return_value={'type':'archive'})
 with patch.object(acces,'connexion',connexion),patch.object(acces,'_lire_ouvert',lecture):
  await outil.ouvrir('/racine/r%C3%A9emploi.zip')
  assert lecture.call_args.args[3]=='/racine/r%C3%A9emploi.zip'
 print('OK : nom littéral, archive refusée avant transfert, fichiers temporaires, compte exact, confinement et droits.')
asyncio.run(main())

"""Rétention explicite et tickets : tests locaux, sans compte ni service réel."""
import sys,os,tempfile,subprocess,time,json
from pathlib import Path
B=Path(sys.argv[1]).resolve();sys.path.insert(0,str(B))
os.environ['DOCUMENTS_DIR']=tempfile.mkdtemp(prefix='livraison-test-')
from security.jetons_ephemeres import emettre,consommer
emettre('websocket','ticket-secret-fictif','utilisateur-fictif',30)
env=dict(os.environ,PYTHONPATH=str(B))
code="from security.jetons_ephemeres import consommer; print(consommer('websocket','ticket-secret-fictif') or '-')"
ps=[subprocess.Popen([sys.executable,'-c',code],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(16)]
r=[p.communicate(timeout=20) for p in ps]
assert all(p.returncode==0 for p in ps),r
assert sum(a.strip()=='utilisateur-fictif' for a,e in r)==1,r
emettre('google_oauth','autre-ticket','emis',30)
assert consommer('websocket','autre-ticket') is None
assert consommer('google_oauth','autre-ticket')=='emis'
assert consommer('google_oauth','autre-ticket') is None
f=Path(os.environ['DOCUMENTS_DIR'])/'auth-ephemere.sqlite3'
assert b'ticket-secret-fictif' not in f.read_bytes()
print('✓ Tickets : 16 consommateurs, un seul succès ; usages isolés, secret non enregistré')
from bureautique import atelier
from stockage.verrous import verrou_fichier
j=atelier.deposer_fichier('ancien.pdf',b'%PDF-1.4 ancien','moi')
fiche=atelier._lire_fiche(j);fiche['termine']=time.time()-90*86400;atelier._ecrire_fiche(j,fiche)
assert atelier.purger()==0 and atelier.chemin_fichier(j,'moi')
for nom in ('ressources.json','index.sqlite','auth-ephemere.sqlite3'):
 p=Path(atelier.DOSSIER)/nom
 if not p.exists():p.write_text('{}')
 os.utime(p,(0,0))
os.environ['DOCUMENTS_RETENTION_JOURS']='30'
with verrou_fichier(atelier.DOSSIER,j):
 assert atelier.purger()==0 and atelier.chemin_fichier(j,'moi')
assert atelier.purger()>0 and not atelier.chemin_fichier(j,'moi')
assert all((Path(atelier.DOSSIER)/n).exists() for n in ('ressources.json','index.sqlite','auth-ephemere.sqlite3'))
print('✓ Aucun effacement par défaut ; purge configurée, document actif protégé, registres conservés')
print('✓ 0 échec')

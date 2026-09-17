"""Le suivi résiste à une longue conversation, aux reprises et à un autre compte."""
import os,sys,tempfile,subprocess
from pathlib import Path
B=Path(sys.argv[1]).resolve();sys.path.insert(0,str(B));os.environ['DOCUMENTS_DIR']=tempfile.mkdtemp(prefix='travail-test-')
from ressources import travail as t
s=t.commencer('A','fil','Prépare le devis. Garde le logo et conserve les tableaux.',0)
source=s['demande_courante']['ref'];assert s['contraintes']
r=s['revision'];assert t.commencer('A','fil','Prépare le devis. Garde le logo et conserve les tableaux.',0)['revision']==r
for i in range(40):t.commencer('A','fil','Suite de travail '+str(i),i+1)
s=t.lire('A','fil');assert 'logo' in t.bloc(s) and s['objectif'].startswith('Prépare')
assert t.lire('B','fil')['contraintes']==[]
assert t.lire('A','autre')['contraintes']==[]
try:t.retenir('B','fil','Garde le logo',source)
except ValueError:pass
else:raise AssertionError('Contrainte d’un autre compte acceptée')
try:t.retenir('A','fil','Utilise un autre logo',source)
except ValueError:pass
else:raise AssertionError('Contrainte inventée acceptée')
ancien=s['contraintes'][0]['id']
s=t.commencer('A','fil','Conserve maintenant seulement le logo bleu.',50)
t.retenir('A','fil','Conserve maintenant seulement le logo bleu.',s['demande_courante']['ref'],ancien)
s=t.lire('A','fil');assert any(x['id']==ancien and not x['active'] for x in s['contraintes'])
t.constater('A','fil',['Préparer','Vérifier'],[{'skill':'envoyer_email','ok':False,'effect_status':'unknown','payload_hash':'h'}])
s=t.lire('A','fil');assert s['resultats'][-1]['effect_status']=='unknown'
env=dict(os.environ,PYTHONPATH=str(B));p=subprocess.run([sys.executable,'-c',"from ressources.travail import lire; assert lire('A','fil')['etapes']==['Préparer','Vérifier']"],env=env,capture_output=True,text=True);assert p.returncode==0,p.stderr
print('✓ 40 échanges sans perdre la contrainte ; identité et fil isolés ; citation exigée ; correction historisée ; effet inconnu conservé ; relecture après redémarrage')
print('✓ 0 échec')

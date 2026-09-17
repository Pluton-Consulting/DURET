"""Concurrence réelle entre processus sur le volume de documents."""
import os,sys,tempfile,subprocess,json
from pathlib import Path
B=Path(sys.argv[1]).resolve();sys.path.insert(0,str(B));os.environ['DOCUMENTS_DIR']=tempfile.mkdtemp(prefix='verrous-test-');env=dict(os.environ,PYTHONPATH=str(B))
from stockage.processus import VerrouProcessus
code="from stockage.processus import VerrouProcessus,Occupe\ntry:\n with VerrouProcessus('conversation:test'):print('acquis')\nexcept Occupe:print('occupe')"
with VerrouProcessus('conversation:test'):
 p=subprocess.run([sys.executable,'-c',code],env=env,capture_output=True,text=True);assert p.returncode==0 and p.stdout.strip()=='occupe',p.stderr
p=subprocess.run([sys.executable,'-c',code],env=env,capture_output=True,text=True);assert p.returncode==0 and p.stdout.strip()=='acquis'
from bureautique import atelier
from stockage.verrous import verrou_fichier
with verrou_fichier(atelier.DOSSIER,'quota:A'):
 code="from bureautique.atelier import ouvrir\ntry:ouvrir({'format':'docx'},'A');print('erreur')\nexcept ValueError:print('occupe')"
 p=subprocess.run([sys.executable,'-c',code],env=env,capture_output=True,text=True);assert p.returncode==0 and p.stdout.strip()=='occupe',p.stderr
j=atelier.ouvrir({'format':'docx'},'A');assert j
from stockage import capacite
ancien=capacite.shutil.disk_usage;capacite.shutil.disk_usage=lambda d:type('U',(),{'free':0})()
try:
 try:atelier.deposer_fichier('x.txt',b'preuve','A');raise AssertionError('Écriture acceptée sans place')
 except ValueError:pass
finally:capacite.shutil.disk_usage=ancien
assert atelier._lire_fiche(j)
print('✓ Verrou interprocessus, libération à la fermeture, quota protégé, manque de place sans effacement')

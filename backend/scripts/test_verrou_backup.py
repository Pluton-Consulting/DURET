"""Deux sauvegardes du même projet ne peuvent pas se chevaucher."""
import os, pathlib, subprocess, sys, tempfile, time, uuid
racine = pathlib.Path(sys.argv[1]).resolve().parent if len(sys.argv)>1 else pathlib.Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory() as td:
    d=pathlib.Path(td); script=d/'travail.sh'
    script.write_text('echo pret > "$1"\nsleep 2\n')
    args=[sys.executable,str(racine/'scripts/verrou_backup.py'),'banc-'+uuid.uuid4().hex,str(script),str(d/'pret')]
    premier=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        fin=time.monotonic()+5
        while not (d/'pret').exists() and time.monotonic()<fin:time.sleep(.02)
        assert (d/'pret').exists(), 'Premier processus non démarré'
        second=subprocess.run(args,capture_output=True,text=True)
        assert second.returncode != 0 and 'déjà en cours' in second.stderr
        assert premier.wait(timeout=5)==0
        suivant=subprocess.run(args,capture_output=True,text=True,timeout=5)
        assert suivant.returncode==0, suivant.stderr
    finally:
        if premier.poll() is None:premier.terminate();premier.wait()
print('✓ 0 échec — exclusion entre processus et libération du verrou')

"""Verrous non bloquants entre workers partageant le volume des documents."""
import fcntl,hashlib,os
from functools import wraps

class Occupe(RuntimeError):pass
class VerrouProcessus:
    def __init__(self,cle):self.cle=cle;self.fd=None
    def __enter__(self):
        from ressources.registre import _chemin
        dossier=_chemin().parent/".verrous-processus";dossier.mkdir(parents=True,exist_ok=True)
        self.fd=os.open(dossier/hashlib.sha256(self.cle.encode()).hexdigest(),os.O_CREAT|os.O_RDWR,0o600)
        try:fcntl.flock(self.fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BaseException as e:
            os.close(self.fd);self.fd=None
            if isinstance(e,BlockingIOError):raise Occupe("Un autre processus exécute déjà ce travail.") from e
            raise
        return self
    def __exit__(self,*exc):
        if self.fd is not None:os.close(self.fd);self.fd=None
        return False

def unique(cle):
    def decorer(f):
        @wraps(f)
        async def executer(*a,**kw):
            verrou=VerrouProcessus(cle)
            try:verrou.__enter__()
            except Occupe:return {"deja_en_cours":True,"en_cours":True,"message":"Campagne déjà active dans un autre worker."}
            try:return await f(*a,**kw)
            finally:verrou.__exit__()
        return executer
    return decorer

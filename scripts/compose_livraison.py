"""Liste explicite des overlays conservés depuis l'installation active."""
import json,sys
from pathlib import Path
BASE=['docker-compose.yml','docker-compose.prod.yml']
def fichiers(root):
    p=Path(root)/'.livraison-compose.json'
    noms=json.loads(p.read_text()) if p.is_file() else BASE
    if noms not in (BASE,BASE+['docker-compose.https.yml']):
        raise ValueError('Topologie de livraison inconnue : aucun overlay ignoré.')
    return list(noms)
if __name__=='__main__':
    print(' '.join('-f '+n for n in fichiers(sys.argv[1])))

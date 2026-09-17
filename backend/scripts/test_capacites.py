"""Les questions d'accès lisent réellement, sans confondre exploration et capacité."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(sys.argv[1] if len(sys.argv)>1 else 'backend').resolve()))
from skills.capacites import premiere_lecture as choisir
nas={'nas_arborescence','lire_mails'};drive={'drive_arborescence','lire_mails'}
assert choisir({'query':'tu as accès au nas ?'},nas)=={'skill':'nas_arborescence','args':{'profondeur':1}}
assert choisir({'query':'liste moi les dossier du drive'},nas)['skill']=='nas_arborescence'
assert choisir({'query':'liste moi les dossier du drive'},drive)['skill']=='drive_arborescence'
assert choisir({'query':'tu as accès aux mails ?'},nas)=={'skill':'lire_mails','args':{'limite':1}}
assert choisir({'query':'tu as accès au nas ?'},set()) is None
for q in ['liste moi tout les dossier du drive','ouvre le dossier IKOS','tu as accès au nas ? supprime ce dossier','ne consulte pas les mails','tu as accès au nas et à mes mails ?']:
 assert choisir({'query':q},nas) is None,q
for k in ['tool_results','tools_finished','redaction_forcee','plan_valide','pending_action','attachments']:
 assert choisir({'query':'tu as accès au nas ?',k:True},nas) is None,k
print('OK : lecture bornée, catalogue du rôle, demandes complètes et négations préservées, pas de boucle.')

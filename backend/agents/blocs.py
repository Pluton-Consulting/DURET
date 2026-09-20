"""UN BLOC ```ui PEUT PORTER PLUSIEURS COMPOSANTS — ET PERSONNE NE LES LISAIT.

Relevé en production le 20/09 (Duret), sur « affiche-les tous » : les quatre
mails du jour. Le modèle avait écrit QUATRE cartes `email` — justes, complètes,
chacune avec son objet, son expéditeur et son extrait — mais dans un SEUL bloc
balisé, une par ligne. C'est ce qu'un modèle écrit naturellement quand une
demande appelle plusieurs composants du même type, et aucune consigne ne le lui
interdisait.

Personne ne savait les lire.

* À l'écran, le lecteur du chat répare un JSON abîmé en RECULANT : devant quatre
  objets à la suite il a tout jeté sauf le premier. L'utilisateur a donc vu UNE
  carte sous un texte qui en annonçait quatre — trois fois de suite, en
  reformulant sa demande. Le travail était juste, c'est l'écran qui mentait.
* Côté serveur, `_BLOC_UI_RE` capture bien tout le contenu du bloc, mais
  `json.loads` refuse quatre objets à la suite. Le bloc devenait donc INVISIBLE
  pour tous les filets : le dédoublonnage, les livrables face au fil, les blocs
  garantis, les images du fil. Une carte `fichier` écrite dans un bloc groupé
  échappait au filet qui vérifie qu'un livrable est à l'écran — qui la
  rajoutait alors en double.

La réponse n'est pas d'interdire au modèle de les grouper. Ce serait une règle
de plus à tenir, il la tiendrait mal, et on aurait troqué une carte manquante
contre un bloc affiché en JSON brut. On ACCEPTE la forme qu'il écrit, et on la
ramène à l'invariant du reste du code : un bloc, un objet. `eclater()` est posée
UNE fois, avant les filets ; tout ce qui suit travaille comme avant.

Le découpage se fait au niveau 0 des accolades, en respectant les chaînes et les
échappements — un « } » à l'intérieur d'un extrait de mail ne coupe rien.
"""

import json as _json
import re as _re

# CE QUE LE MODÈLE A OUVERT, clôturé ou non — ce n'est PAS le motif qui sert
# à lire un composant (celui-là exige les trois accents finaux, et vit dans
# `agent1._BLOC_UI_RE`). Les deux répondent à des questions différentes : « un
# bloc complet » là-bas, « tout ce que le modèle a commencé » ici. Un bloc
# tranché net par le plafond de sortie n'a pas sa clôture ; s'il portait quatre
# cartes, les trois premières sont pourtant entières et n'ont aucune raison
# d'être perdues avec la quatrième.
_BLOC_OUVERT_RE = _re.compile(r"```ui[ \t]*\n?[ \t]*(\{.*?)(?:```|$)", _re.S)


def objets(brut: str) -> list[str]:
    """Les objets JSON de premier niveau d'un bloc, dans l'ordre.

    Un objet complet ferme ses accolades : on coupe là. Ce qui reste ouvert à la
    fin forme un dernier morceau — c'est le cas d'un bloc tranché par le plafond
    de sortie, et c'est au lecteur de l'écran de le réparer.

    Un bloc à un seul objet rend un seul morceau : rien ne change pour lui.
    """
    if not isinstance(brut, str):
        return []
    morceaux: list[str] = []
    debut, profondeur, chaine, echap = -1, 0, False, False
    for i, c in enumerate(brut):
        if echap:
            echap = False
            continue
        if c == "\\":
            echap = True
            continue
        if chaine:
            if c == '"':
                chaine = False
            continue
        if c == '"':
            chaine = True
            continue
        if c in "{[":
            if profondeur == 0 and debut < 0:
                debut = i
            profondeur += 1
        elif c in "}]":
            profondeur = max(0, profondeur - 1)
            if profondeur == 0 and debut >= 0:
                morceaux.append(brut[debut:i + 1])
                debut = -1
    if debut >= 0:
        morceaux.append(brut[debut:])
    return morceaux or ([brut] if isinstance(brut, str) and brut.strip() else [])


def eclater(texte: str) -> str:
    """Un bloc ```ui par composant.

    PRUDENTE PAR CONSTRUCTION : un bloc qui ne porte qu'un objet n'est pas
    touché, et un bloc dont un morceau du MILIEU est illisible est laissé tel
    quel — on ne casse jamais ce que le code d'aujourd'hui sait déjà traiter.
    Seul un dernier morceau illisible (bloc tranché en plein vol) est écarté :
    il était de toute façon perdu, puisque l'écran ne relit que le premier.
    """
    if not isinstance(texte, str) or "```ui" not in texte:
        return texte

    def _un(m):
        morceaux = objets(m.group(1))
        if len(morceaux) < 2:
            return m.group(0)
        gardes: list[str] = []
        for rang, morceau in enumerate(morceaux):
            try:
                bloc = _json.loads(morceau)
            except ValueError:
                if rang == len(morceaux) - 1:
                    break          # tranché en fin de bloc : déjà perdu
                return m.group(0)  # illisible au milieu : on ne touche à rien
            if not isinstance(bloc, dict) or not bloc.get("type"):
                return m.group(0)  # pas un composant : c'est au texte de le dire
            gardes.append(_json.dumps(bloc, ensure_ascii=False))
        if len(gardes) < 2:
            return m.group(0)
        return "\n\n".join("```ui\n" + g + "\n```" for g in gardes)

    return _BLOC_OUVERT_RE.sub(_un, texte)

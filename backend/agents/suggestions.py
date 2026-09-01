"""Le filet des suggestions : une suite proposée à la fin de CHAQUE réponse.

POURQUOI CE FILET (01/09, demande de Noa « des suggestions à la fin de chaque
message »). La seule source de suggestions était une phrase du prompt et un
convertisseur étroit (`options_proposees`, qui n'agit que sur une question à
choix numérotée écrite en prose). Résultat mesuré : la plupart des réponses n'en
portaient aucune — et JAMAIS celles qui passent par un filet mécanique (le rendu
de secours réécrit la prose dans un contexte réduit qui ne connaît même pas le
catalogue de composants), ni la vision (agent2 ne passe pas par
`rehydrate_node`), ni la reprise après validation (`execute_action_node` non
plus). C'est-à-dire : jamais aux moments où une suite est la plus évidente —
juste après un visuel tiré, un mail envoyé, un fichier déposé.

CE N'EST PAS UNE PHRASE ÉCRITE EN DUR, et c'est la seule raison pour laquelle ce
module a le droit d'exister. Une suggestion est un RACCOURCI D'ENTRÉE, du même
statut exact que le menu éclair de la barre de saisie
(`frontend/lib/raccourcis.ts`, accepté le 31/08) ou que le bloc `plan` construit
mécaniquement : elle est écrite du point de vue de l'utilisateur, à l'impératif,
elle ne raconte rien de ce qui a été fait et ne pose aucune question. Elle ne
peut donc pas se lire comme la prose de l'assistant.

ET ELLE NE CONTIENT AUCUNE DONNÉE DU TOUR : que du vocabulaire fixe (le banc le
vérifie). C'est ce qui permet de la poser APRÈS la réhydratation — donc sur du
texte en clair — sans qu'un jeton puisse fuir, et de ne jamais l'écrire dans
l'historique du modèle.

Module PUR : aucune base, aucun réseau, aucun appel LLM. Le vocabulaire, lui,
est du métier et vit dans `agents/suggestions_metier.py` (fichier par client).
"""
import json as _json
import re

from agents.suggestions_metier import (DEFAUT, ERREUR, PAR_BLOC, PAR_EXPERT,
                                       PAR_SKILL)

# Trois au maximum : au-delà, la rangée déborde de la bulle et le choix cesse
# d'en être un. 48 caractères : une pastille plus longue se coupe à l'écran (la
# rangée `Suggestions` d'AI Elements DÉFILE, elle ne replie pas les libellés).
MAX_OPTIONS = 3
MAX_LONGUEUR = 48

_BLOC_UI_RE = re.compile(r"```ui\s*(\{.*?\})\s*```", re.S)
# Les blocs qui portent DÉJÀ leur propre interaction : y ajouter des pastilles
# ferait deux jeux de boutons pour une seule décision.
_BLOCS_INTERACTIFS = ("plan", "reponses_mail", "quick_replies")
# L'ordre de préférence quand plusieurs blocs sont à l'écran : du plus
# spécifique (une image, un fichier) au plus générique (un tableau).
_ORDRE_BLOCS = ("visuel", "fichier", "arbre", "quote", "email", "site", "table")


def _types_presents(texte: str) -> set:
    """Les types de blocs ```ui du message, lus sur le JSON PARSÉ.

    Pas par sous-chaîne : le projet a déjà payé une fois la recherche
    approximative dans du texte (`_livrables_a_l_ecran`, 29/08 — un modèle qui
    échappe les barres obliques rendait le bloc introuvable).
    """
    types = set()
    for brut in _BLOC_UI_RE.findall(texte or ""):
        try:
            bloc = _json.loads(brut)
        except ValueError:
            continue
        if isinstance(bloc, dict) and bloc.get("type"):
            types.add(str(bloc["type"]))
    return types


def _tailler(options) -> list:
    """Les bornes d'écran, appliquées ICI et pas dans la table : la table est du
    métier, les bornes sont de la mécanique.

    Une seule option restante rend `[]` : un choix unique n'est pas un choix,
    c'est un bouton qui pousse — exactement ce qu'on ne veut pas.
    """
    vues, propres = set(), []
    for o in options or []:
        libelle = str(o or "").strip()
        if not libelle or len(libelle) > MAX_LONGUEUR or libelle.lower() in vues:
            continue
        vues.add(libelle.lower())
        propres.append(libelle)
    return propres[:MAX_OPTIONS] if len(propres) >= 2 else []


def suggestions_du_tour(texte: str, resultats=None, *, expert: str = "",
                        pending: bool = False) -> list:
    """Les suites à proposer, ou [] quand ça n'aurait pas de sens.

    L'ordre de choix va du PLUS PRÉCIS au plus général : le dernier skill qui a
    RÉUSSI (c'est lui qui dit ce qui vient de se passer), sinon un bloc à
    l'écran, sinon l'expert qui a répondu, sinon le socle. Un tour où rien n'a
    abouti reçoit les raccourcis d'échec — trois portes qui marchent, aucun
    commentaire sur l'échec.
    """
    if pending:
        return []            # une validation attend : une seule décision à la fois
    if not (texte or "").strip():
        return []
    types = _types_presents(texte)
    if types & set(_BLOCS_INTERACTIFS):
        return []            # le modèle a déjà proposé, ou le bloc porte ses boutons

    resultats = list(resultats or [])
    for r in reversed(resultats):        # le dernier geste réussi fait foi
        if isinstance(r, dict) and r.get("ok") and r.get("skill") in PAR_SKILL:
            return _tailler(PAR_SKILL[r["skill"]])
    for t in _ORDRE_BLOCS:
        if t in types and t in PAR_BLOC:
            return _tailler(PAR_BLOC[t])
    if resultats and not any(isinstance(r, dict) and r.get("ok") for r in resultats):
        return _tailler(ERREUR)
    if expert in PAR_EXPERT:
        return _tailler(PAR_EXPERT[expert])
    return _tailler(DEFAUT)


def suites_d_echec() -> list:
    """Les raccourcis d'un tour qui n'a rien produit — trois portes ouvertes."""
    return _tailler(ERREUR)


def poser(texte: str, options) -> str:
    """Ajoute la rangée à la fin du texte. Ne réécrit JAMAIS ce qui précède."""
    if not options:
        return texte
    bloc = _json.dumps({"type": "quick_replies", "options": list(options)},
                       ensure_ascii=False)
    return (texte or "").rstrip() + "\n\n```ui\n" + bloc + "\n```"

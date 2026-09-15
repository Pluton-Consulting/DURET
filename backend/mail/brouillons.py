"""
LE DERNIER BROUILLON DE LA CONVERSATION — ce qu'on retouche, ce qu'on dépose.

Relevé du 11/09 (Symbiose, deux conversations) : « fais une version un peu
moins brute », « tu as enlevé trop de choses, le mail d'avant était mieux
construit », « fais le lien avec mes demandes précédentes ». `redaction_email`
repartait À CHAQUE FOIS du seul `contexte` que le modèle voulait bien lui
passer : la version que la personne venait de valider n'entrait pas dans
l'appel, et chaque retouche était une réécriture — des phrases perdues, une
signature revenue, une structure changée. Et « mets-le dans mes brouillons »
n'avait rien à déposer que le modèle ne dût recopier de mémoire.

Le serveur retient donc le dernier brouillon produit PAR CONVERSATION (et par
personne) : `redaction_email` avec `retoucher` part de lui, `deposer_brouillon`
sans corps le prend tel quel. En mémoire du processus, borné, 24 h : un
redémarrage le perd, et le modèle peut toujours le repasser explicitement.

Module PUR : le banc l'exerce tel quel.
"""
from __future__ import annotations

import time

DUREE_S = 24 * 3600
MAX_FILS = 500

_DERNIERS: dict = {}


def _cle(user_id, fil) -> tuple:
    return (str(user_id or ""), str(fil or ""))


def retenir(user_id, fil, brouillon: dict) -> None:
    """Retient {objet, corps, destinataire, ref, boite} pour cette conversation."""
    if not fil or not isinstance(brouillon, dict) or not brouillon.get("corps"):
        return
    if len(_DERNIERS) >= MAX_FILS:
        for cle in sorted(_DERNIERS, key=lambda k: _DERNIERS[k][1])[: MAX_FILS // 5]:
            _DERNIERS.pop(cle, None)
    garde = {k: brouillon.get(k) for k in ("objet", "corps", "destinataire", "ref", "boite")
             if brouillon.get(k)}
    _DERNIERS[_cle(user_id, fil)] = (garde, time.monotonic())


def dernier(user_id, fil) -> dict | None:
    """Le dernier brouillon de cette conversation pour cette personne, ou None."""
    garde = _DERNIERS.get(_cle(user_id, fil))
    if not garde or time.monotonic() - garde[1] > DUREE_S:
        return None
    return dict(garde[0])

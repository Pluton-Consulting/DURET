"""
CE QU'UN GESTE A VRAIMENT DONNÉ — le résultat normalisé d'un skill (16/09, audit D-05/S-05).

L'enveloppe d'exécution rendait `ok=True` dès que la fonction Python se
terminait, même quand sa sortie disait elle-même l'échec : `{"ok": False,
"message": "Consigne trop courte"}`, `{"depose": False}`, `{"genere": False}`.
Le journal, la console et les filets comptaient alors un échec comme une
réussite, et le modèle pouvait écrire « c'est fait ».

Ce module lit les CONTRATS CONNUS des sorties et rend un résultat typé, SANS
retirer aucun champ existant (les appelants legacy lisent toujours `ok` et
`output`) :

  outcome        success | partial | not_found | denied | failed | pending | unverified
  ok             False seulement pour failed et denied — le reste garde son
                 comportement d'avant (une recherche vide n'est pas une panne)
  effect_status  none (lecture) | done | not_done | pending | unknown
  evidence_refs  les références que la sortie porte (document, visuel, pièce…)
  warnings       ce qui mérite d'être dit (couverture partielle…)
  retryable      un nouvel essai a-t-il un sens ?

`unverified` : une sortie qu'aucun contrat connu ne décrit. Elle n'est PAS
promue en échec (des dizaines de skills rendent des comptes rendus libres, et
les casser serait pire), mais elle est marquée et journalisée comme telle —
jamais comptée comme une preuve de réussite vérifiée.
"""
from __future__ import annotations

import re

OUTCOMES = ("success", "partial", "not_found", "denied", "failed", "pending", "unverified")

# Les clés qui DISENT le résultat métier. L'ordre compte : la première qui
# tranche l'emporte.
_ECHEC_SI_FAUX = ("ok", "depose", "genere", "applique", "enregistre", "reussi", "abouti")
_INTROUVABLE_SI_FAUX = ("trouve", "trouvee")
_STATUTS_ECHEC = {"echec", "échec", "erreur", "failed", "error", "refuse", "refusé"}
_STATUTS_ATTENTE = {"en_attente", "pending", "attente_validation", "pending_validation"}
_RE_DOCUMENT = re.compile(r"/api/documents/([A-Za-z0-9_-]{8,64})")
_RE_VISUEL = re.compile(r"/api/visuels/([A-Za-z0-9]{8,64})")


def _preuves(sortie: dict) -> list[str]:
    """Les références que porte la sortie : ce qui pourra être rouvert."""
    refs: list[str] = []
    texte = " ".join(str(sortie.get(k) or "") for k in ("url", "fichier_url"))
    bloc = sortie.get("bloc_ui")
    blocs = bloc if isinstance(bloc, list) else ([bloc] if isinstance(bloc, dict) else [])
    for b in blocs:
        if isinstance(b, dict):
            texte += " " + str(b.get("url") or "")
            for image in b.get("images") or []:
                if isinstance(image, dict) and image.get("cle"):
                    refs.append(f"visuel:{image['cle']}")
    refs += [f"document:{j}" for j in _RE_DOCUMENT.findall(texte)]
    refs += [f"visuel:{c}" for c in _RE_VISUEL.findall(texte)]
    for cle, prefixe in (("document_id", "document"), ("cles", "visuel"), ("ref", "ref"),
                         ("brouillon_id", "brouillon"), ("message_id", "message")):
        valeur = sortie.get(cle)
        if isinstance(valeur, str) and valeur:
            refs.append(f"{prefixe}:{valeur}")
        elif isinstance(valeur, list):
            refs += [f"{prefixe}:{v}" for v in valeur if isinstance(v, str) and v]
    vus, uniques = set(), []
    for r in refs:
        if r not in vus:
            vus.add(r)
            uniques.append(r)
    return uniques[:20]


def _issue(sortie) -> tuple[str, list[str], bool]:
    """(outcome, avertissements, contrat_reconnu)."""
    if not isinstance(sortie, dict):
        return "unverified", [], False
    avertissements: list[str] = []
    for cle in _ECHEC_SI_FAUX:
        if sortie.get(cle) is False:
            return "failed", avertissements, True
    if sortie.get("refuse") is True or sortie.get("acces_refuse") is True:
        return "denied", avertissements, True
    statut = str(sortie.get("statut") or sortie.get("status") or "").strip().lower()
    if statut in _STATUTS_ECHEC:
        return "failed", avertissements, True
    if statut in _STATUTS_ATTENTE or sortie.get("en_attente") is True:
        return "pending", avertissements, True
    erreur = sortie.get("erreur") or sortie.get("error")
    if isinstance(erreur, str) and erreur.strip() and sortie.get("ok") is not True:
        return "failed", avertissements, True
    for cle in _INTROUVABLE_SI_FAUX:
        if sortie.get(cle) is False:
            return "not_found", avertissements, True
    if sortie.get("complet") is False or sortie.get("partiel") is True or sortie.get("tronque") is True:
        avertissements.append("résultat partiel : la source n'a pas été couverte en entier")
        return "partial", avertissements, True
    reconnu = any(sortie.get(c) is True for c in _ECHEC_SI_FAUX + _INTROUVABLE_SI_FAUX
                  + ("envoye", "pret", "cree", "termine"))
    if reconnu:
        return "success", avertissements, True
    return "unverified", avertissements, False


def normaliser_resultat(sortie, effet: str = "lecture") -> dict:
    """Le résultat typé d'une sortie de skill (voir l'en-tête du module)."""
    outcome, avertissements, reconnu = _issue(sortie)
    if effet == "lecture":
        effect_status = "none"
    elif outcome in ("success", "partial"):
        effect_status = "done"
    elif outcome in ("failed", "denied", "not_found"):
        effect_status = "not_done"
    elif outcome == "pending":
        effect_status = "pending"
    else:
        # Un effet dont la sortie ne dit rien de précis : on ne l'affirme pas.
        effect_status = "unknown" if effet == "externe" else "done"
    return {
        "outcome": outcome,
        "ok": outcome not in ("failed", "denied"),
        "effect_status": effect_status,
        "evidence_refs": _preuves(sortie) if isinstance(sortie, dict) else [],
        "warnings": avertissements,
        "retryable": outcome == "failed" and not (isinstance(sortie, dict) and sortie.get("definitif")),
        "contrat_reconnu": reconnu,
    }


def message_d_echec(sortie) -> str:
    """La phrase d'échec qu'une sortie porte, pour la dire telle quelle."""
    if isinstance(sortie, dict):
        for cle in ("message", "erreur", "error", "raison", "detail"):
            v = sortie.get(cle)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return "l'action n'a pas abouti"

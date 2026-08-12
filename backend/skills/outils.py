"""
Skills de la bibliothèque d'outils — la couche qui parle au modèle.

Chaque skill valide ses paramètres, appelle la fonction composée, et rend un
échec comme un ÉCHEC (`SkillError`). Les fonctions de `outils/` ne connaissent
ni l'utilisateur ni le protocole d'action : elles font le travail, c'est ici
qu'on branche l'identité et les droits.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("duret.skills.outils")


def _echec(message: str):
    from skills.executor import SkillError
    raise SkillError(message)


def _proprietaire(user) -> str:
    return str(getattr(user, "id", "") or "")


async def _garde_nas(user):
    """Le NAS est réservé à certains rôles. Composer n'ouvre aucun droit."""
    from nas.acces import verifier_role
    verifier_role(user)


# ── Serveur de fichiers ──────────────────────────────────────────────

async def nas_apercu(data: dict, user) -> dict:
    """Compte et classe le contenu d'un dossier, sans en lister le détail."""
    from outils.nas import apercu
    await _garde_nas(user)
    try:
        return await apercu((data.get("chemin") or "").strip() or None)
    except Exception as e:  # noqa: BLE001
        _echec(str(getattr(e, "detail", None) or e))


async def nas_arborescence(data: dict, user) -> dict:
    """L'arbre d'un dossier sur plusieurs niveaux, en un appel."""
    from outils.nas import arborescence
    await _garde_nas(user)
    chemin = (data.get("chemin") or "").strip()
    if not chemin:
        _echec("Donne le `chemin` du dossier dont tu veux l'arborescence.")
    try:
        return await arborescence(chemin, data.get("profondeur") or 2)
    except Exception as e:  # noqa: BLE001
        _echec(str(getattr(e, "detail", None) or e))


async def nas_ouvrir(data: dict, user) -> dict:
    """Lit un fichier depuis son nom, sans en connaître le chemin."""
    from outils.nas import ouvrir
    await _garde_nas(user)
    quoi = (data.get("nom") or data.get("chemin") or "").strip()
    if not quoi:
        _echec("Donne le `nom` du fichier à ouvrir (ou son `chemin` complet).")
    try:
        return await ouvrir(quoi)
    except Exception as e:  # noqa: BLE001
        _echec(str(getattr(e, "detail", None) or e))


async def nas_lire_lot(data: dict, user) -> dict:
    """Lit plusieurs fichiers correspondant à un motif."""
    from outils.nas import lire_lot
    await _garde_nas(user)
    motif = (data.get("motif") or "").strip()
    if not motif:
        _echec("Donne le `motif` des fichiers à lire (un morceau de leur nom).")
    try:
        return await lire_lot(motif, (data.get("dossier") or "").strip() or None,
                              data.get("limite") or 5)
    except Exception as e:  # noqa: BLE001
        _echec(str(getattr(e, "detail", None) or e))


async def nas_deposer_document(data: dict, user) -> dict:
    """Finalise un document en cours et le dépose sur le serveur. EFFET EXTERNE."""
    from outils.nas import deposer_document
    await _garde_nas(user)
    doc = (data.get("document_id") or "").strip()
    dossier = (data.get("dossier") or "").strip()
    if not doc or not dossier:
        _echec("`document_id` et `dossier` sont requis.")
    try:
        return await deposer_document(doc, dossier, _proprietaire(user),
                                      (data.get("nom") or "").strip() or None)
    except Exception as e:  # noqa: BLE001
        _echec(str(getattr(e, "detail", None) or e))


# ── Documents ────────────────────────────────────────────────────────

async def produire_document(data: dict, user) -> dict:
    """Crée, remplit et finalise un document en un seul appel."""
    from outils.documents import produire

    proprio = _proprietaire(user)
    if not proprio:
        _echec("Impossible de produire un document sans compte identifié.")
    titre = (data.get("titre") or "").strip()
    if not titre:
        _echec("Donne un `titre` au document.")

    blocs = data.get("blocs") or data.get("elements") or data.get("contenu")
    if isinstance(blocs, dict):
        blocs = [blocs]
    try:
        return await produire(
            titre=titre, blocs=blocs, proprietaire=proprio,
            format=(data.get("format") or "pdf").strip().lower(),
            entete=(data.get("entete") or "").strip(),
            pied=(data.get("pied") or "").strip(),
            numeroter=data.get("numeroter", True))
    except Exception as e:  # noqa: BLE001
        _echec(str(getattr(e, "detail", None) or e))


# ── Mode d'emploi ────────────────────────────────────────────────────

async def mode_emploi(data: dict, user) -> dict:
    """Le mode d'emploi complet d'un outil, à la demande.

    Ce texte n'est PAS injecté dans le prompt : c'est tout son intérêt. Les
    conventions de chemin, le vocabulaire maison, les limites et les pannes
    connues pèsent des milliers de caractères qu'on ne peut pas faire porter à
    chaque tour, y compris à ceux qui n'ouvrent aucun fichier.
    """
    from outils import mode_emploi as lire_doc, outils_disponibles
    nom = (data.get("outil") or "").strip()
    if not nom:
        return {"outils": [{"nom": n, "libelle": l} for n, l in outils_disponibles()],
                "note": "Précise `outil` pour obtenir son mode d'emploi."}
    return {"outil": nom, "mode_emploi": lire_doc(nom)}

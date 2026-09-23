"""
LES BOÎTES PRIVÉES DE LA DIRECTION (23/09, Duret).

Demande de Noa : « on va à l'avenir être amenés à connecter deux mails
perso/pro supplémentaires, mais uniquement pour le compte direction (et donc
admin) ; ils doivent techniquement être inaccessibles depuis un compte autre
que direction ».

CE QUE C'EST. Deux emplacements, chacun une boîte IMAP ouverte par un mot de
passe d'application (Gmail, Outlook.com, OVH… : IMAP et SMTP sont partout les
mêmes). Ils s'ajoutent à la boîte unique de l'entreprise sans la remplacer :
`mail.imap.boite_unique()` et tout ce qui en dépend (lecture par défaut,
courrier entrant, synchronisation de la mémoire) ne les voient jamais.

INACCESSIBLES, TECHNIQUEMENT — trois verrous, tous côté serveur :
  * `mail.authorization.verifier_acces`, le point de passage OBLIGATOIRE de
    tout geste mail, refuse une boîte privée à tout rôle hors `ROLES`, avec le
    MÊME message qu'une boîte inconnue (on ne révèle pas qu'elle existe) ;
  * `boites_autorisees` et `boites_visibles` ne la NOMMENT qu'à ces rôles :
    un profil terrain ne peut ni la lire, ni même apprendre son adresse ;
  * elle n'entre JAMAIS dans la mémoire partagée : ni l'ingestion, ni la
    collecte de style, ni le courrier entrant ne la lisent (ils ne connaissent
    que la boîte unique). Ce qu'on en lit reste dans la conversation de la
    personne de direction qui l'a demandé.

LES IDENTIFIANTS vivent dans `cles_api` (même table, même cache, même priorité
que la boîte unique) et ne ressortent jamais : seule leur empreinte s'affiche.

QUELLE BOÎTE UN APPEL IMAP OUVRE : `mail.imap` choisit ses identifiants selon
l'adresse visée (`identifiants`), et, pour les appels qui ne la connaissent
pas (pièce jointe, dépôt d'un brouillon, indicateurs), selon la boîte que
`verifier_acces` vient d'autoriser pour CE geste (`mail.imap.boite_du_geste`).
"""
from __future__ import annotations

import re
from typing import Optional

# Les seuls rôles qui voient ces boîtes. Une liste FERMÉE, écrite ici et nulle
# part ailleurs : un rôle inventé demain n'y entre pas par défaut.
ROLES = frozenset({"direction", "super_admin"})

EMPLACEMENTS = (1, 2)
HOTE_IMAP_DEFAUT = "imap.gmail.com"
HOTE_SMTP_DEFAUT = "smtp.gmail.com"

_ADRESSE_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def cles(rang: int) -> dict:
    """Les noms des réglages (`cles_api`) d'un emplacement."""
    p = f"mail_prive_{int(rang)}_"
    return {"adresse": p + "user", "mot_de_passe": p + "password", "libelle": p + "libelle",
            "hote_imap": p + "imap_host", "hote_smtp": p + "smtp_host"}


def toutes_les_cles() -> tuple:
    return tuple(v for r in EMPLACEMENTS for v in cles(r).values())


def _valeur(nom: str) -> str:
    try:
        from llm.cles import valeur
        return str(valeur(nom) or "").strip()
    except Exception:  # noqa: BLE001 — sans cache de clés, aucune boîte privée
        return ""


def peut_acceder(role: Optional[str]) -> bool:
    """Le rôle voit-il les boîtes privées ? Fail-closed : inconnu = non."""
    return (role or "").strip().lower() in ROLES


def emplacement(rang: int) -> dict:
    """Ce qu'un emplacement porte — JAMAIS le mot de passe, seulement s'il est posé."""
    c = cles(rang)
    adresse = _valeur(c["adresse"]).lower()
    return {"rang": int(rang), "adresse": adresse or None,
            "libelle": _valeur(c["libelle"]) or f"Boîte privée {rang}",
            "hote_imap": _valeur(c["hote_imap"]) or HOTE_IMAP_DEFAUT,
            "hote_smtp": _valeur(c["hote_smtp"]) or HOTE_SMTP_DEFAUT,
            "mot_de_passe_pose": bool(_valeur(c["mot_de_passe"])),
            "configuree": bool(adresse and _valeur(c["mot_de_passe"]))}


def boites() -> list[dict]:
    """Les boîtes privées CONFIGURÉES (adresse et mot de passe posés)."""
    return [e for e in (emplacement(r) for r in EMPLACEMENTS) if e["configuree"]]


def _normaliser(adresse: Optional[str]) -> str:
    return (adresse or "").strip().lower()


def est_privee(adresse: Optional[str]) -> bool:
    """Cette adresse est-elle une boîte privée configurée ?

    La boîte unique de l'entreprise n'en est JAMAIS une, même si quelqu'un la
    saisissait aussi ici : elle reste lisible de tous ceux qui ont l'accès au
    mail, et la saisir deux fois ne doit pas la retirer à l'équipe.
    """
    cible = _normaliser(adresse)
    if not cible:
        return False
    try:
        from mail.imap import boite_unique
        if cible == (boite_unique() or ""):
            return False
    except Exception:  # noqa: BLE001
        pass
    return any(b["adresse"] == cible for b in boites())


def identifiants(adresse: Optional[str]) -> Optional[dict]:
    """(adresse, mot de passe, hôtes) d'une boîte privée, ou None."""
    cible = _normaliser(adresse)
    if not est_privee(cible):
        return None
    for r in EMPLACEMENTS:
        c = cles(r)
        if _valeur(c["adresse"]).lower() == cible:
            return {"adresse": cible,
                    "mot_de_passe": _valeur(c["mot_de_passe"]).replace(" ", ""),
                    "hote_imap": _valeur(c["hote_imap"]) or HOTE_IMAP_DEFAUT,
                    "hote_smtp": _valeur(c["hote_smtp"]) or HOTE_SMTP_DEFAUT}
    return None


def adresses_pour(role: Optional[str]) -> list[str]:
    """Les adresses privées qu'on peut NOMMER à ce rôle — vide pour tous les
    autres : l'adresse elle-même ne doit pas leur parvenir."""
    if not peut_acceder(role):
        return []
    return [b["adresse"] for b in boites()]


def resoudre_libelle(demande: Optional[str], role: Optional[str]) -> Optional[str]:
    """« perso », « ma boîte pro », « boîte privée 2 » → l'adresse, pour ces
    rôles seulement. Rien pour les autres : pas même une résolution."""
    if not peut_acceder(role):
        return None
    texte = _normaliser(demande)
    if not texte:
        return None
    for b in boites():
        libelle = _normaliser(b["libelle"])
        if texte == b["adresse"] or (libelle and (texte == libelle or (
                len(libelle) >= 3 and libelle in texte) or (len(texte) >= 3 and texte in libelle))):
            return b["adresse"]
        if re.search(rf"\b(priv[ée]e?|boite|boîte)\s*{b['rang']}\b", texte):
            return b["adresse"]
    return None


def adresse_valide(adresse: str) -> bool:
    return bool(_ADRESSE_RE.match(adresse or ""))

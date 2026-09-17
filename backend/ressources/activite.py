"""
CE QUI SE FAIT EN CE MOMENT, DIT À L'ÉCRAN (17/09).

Relevé de Noa : « on voit le même texte pendant trois minutes, c'est beaucoup
trop long ». Un travail de fond passe l'essentiel de son temps DANS un appel au
modèle (une à trois minutes) : dire « rédaction de la rubrique X » ne suffit
pas, il faut dire ce qui se passe PENDANT — la demande est partie, le modèle
répond depuis tant de secondes, il a dépassé son délai et le secours prend le
relais, la réponse est arrivée et ses citations se vérifient, elle est à
corriger pour telle raison. Chaque geste long pose son ACTIVITÉ (`dire`), et
tout ce qui se passe dessous la PRÉCISE (`preciser`) sans avoir à connaître le
travail : l'activité voyage dans le contexte de la tâche asyncio.

Rien ici ne peut faire échouer un travail : toute erreur d'écriture est avalée.
"""
from __future__ import annotations

import asyncio
import contextvars
import time

_COURANTE: contextvars.ContextVar = contextvars.ContextVar("activite_documentaire", default=None)
RECENTES = 4          # activités gardées (des appels tournent en parallèle)


def _ecrire(uid, fil, tache, entree: dict, finie: str | None = None) -> None:
    from ressources import dossiers
    ancien = dossiers.etape(uid, fil, tache, "activite") or {}
    # `finie` : l'activité que CE fil d'exécution vient de quitter — elle n'est plus
    # « en parallèle » (l'écran citait encore la lecture des images une fois finie).
    liste = [x for x in (ancien.get("liste") or []) if isinstance(x, dict) and x.get("id") not in (entree["id"], finie)]
    liste = (liste + [entree])[-RECENTES:]
    dossiers.etape(uid, fil, tache, "activite", {"texte": entree["texte"], "a": entree["a"], "liste": liste})


async def dire(uid, fil, tache, texte: str) -> None:
    """Pose l'activité de la tâche courante : ce qu'on fait, sur quoi."""
    try:
        entree = {"id": f"{time.time():.6f}", "texte": str(texte)[:240], "a": time.time(), "detail": "", "d": time.time()}
        precedente = _COURANTE.get()
        _COURANTE.set((uid, fil, tache, entree))
        await asyncio.to_thread(_ecrire, uid, fil, tache, dict(entree), precedente[3]["id"] if precedente else None)
    except Exception:  # noqa: BLE001
        pass


async def preciser(detail: str) -> None:
    """Précise l'activité courante (« le modèle répond », « secours », « à corriger »)."""
    try:
        courante = _COURANTE.get()
        if not courante:
            return
        uid, fil, tache, entree = courante
        entree["detail"] = str(detail)[:200]
        entree["d"] = time.time()
        await asyncio.to_thread(_ecrire, uid, fil, tache, dict(entree))
    except Exception:  # noqa: BLE001
        pass


def _duree(secondes: float) -> str:
    s = max(0, int(secondes))
    return f"{s} s" if s < 60 else f"{s // 60} min {s % 60:02d}"


def phrase(activite, maintenant: float | None = None) -> str:
    """Le texte d'écran : l'activité la plus récente, son détail, depuis quand,
    et ce qui tourne en parallèle. Vide si rien de récent (15 min)."""
    if not isinstance(activite, dict):
        return ""
    maintenant = maintenant or time.time()
    liste = [x for x in (activite.get("liste") or []) if isinstance(x, dict)] or [
        {"texte": activite.get("texte"), "a": activite.get("a"), "detail": "", "d": activite.get("a")}]
    vives = [x for x in liste if maintenant - float(x.get("d") or x.get("a") or 0) < 900 and x.get("texte")]
    if not vives:
        return ""
    derniere = max(vives, key=lambda x: float(x.get("d") or 0))
    texte = str(derniere["texte"])
    if derniere.get("detail"):
        texte += " · " + str(derniere["detail"]) + " (depuis " + _duree(maintenant - float(derniere.get("d") or maintenant)) + ")"
    else:
        texte += " (depuis " + _duree(maintenant - float(derniere.get("a") or maintenant)) + ")"
    autres = [x for x in vives if x is not derniere and maintenant - float(x.get("d") or 0) < 240]
    if autres:
        texte += " — en parallèle : " + " ; ".join(str(x["texte"])[:90] for x in autres[-2:])
    return texte

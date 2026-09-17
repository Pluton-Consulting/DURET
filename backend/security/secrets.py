"""
AUCUNE CLÉ NE SORT — journaux, traces, exports (27/08, élargi le 16/09, audit D-22/S-22).

Relevé le 27/08 en lisant `docker compose logs backend` : httpx journalise en
INFO chaque requête avec son URL COMPLÈTE, et les API Google portent la clé dans
la query string. La clé s'affichait donc en clair, lisible par quiconque ouvre
les journaux ou en poste une capture. Aucune ligne du projet ne l'écrivait :
c'est la bibliothèque HTTP qui la recopiait.

CE QUE L'AUDIT A TROUVÉ (D-22/S-22). Le filtre était posé sur le LOGGER RACINE. Or,
en Python, un enregistrement émis par `logging.getLogger("duret.mail")` ne passe
PAS par les filtres de la racine : il remonte vers ses HANDLERS. Tout ce que
journalisait le reste de l'application échappait donc au masquage. Et une
exception (`exc_info`) sort par le formateur, jamais par `msg`.

Ici : le motif, le masquage (texte et structures), et la pose du filtre sur les
handlers — appelée au démarrage puis relancée après que le serveur a installé
les siens. Le même masquage sert à l'export des traces (`observability`).

Le filtre garde les SIX DERNIERS caractères : c'est ce qui permet de dire
« c'est bien la clé du fichier de configuration, pas celle de la base » sans
jamais livrer la clé elle-même.
"""
from __future__ import annotations

import logging
import re

MOTIF = re.compile(
    r"(?i)\b(key|api[_-]?key|(?:access|refresh|id)[_-]?token|token|ticket|apikey|password|(?:client[_-]?)?secret)"
    r"(=|%3D|[\"']?\s*:\s*[\"']?)([^\s\"'&,;<>]{12,})")
_CLE_SECRETE = re.compile(r"(?i)^(?:api[_-]?key|apikey|key|(?:access|refresh|id)[_-]?token|token|ticket|password|(?:client[_-]?)?secret|authorization|cookie|set-cookie)$")
_BEARER = re.compile(r"(?i)\b(Bearer\s+)([A-Za-z0-9._~+/=-]+)")


def masquer(texte: str) -> str:
    """Le texte, clés remplacées par « ***<six derniers caractères> »."""
    def _remplacer(m):
        valeur = m.group(3)
        return f"{m.group(1)}{m.group(2)}***{valeur[-6:]}"
    return _BEARER.sub(lambda m: m.group(1) + "***", MOTIF.sub(_remplacer, texte))


def masquer_arbre(valeur, profondeur: int = 0):
    """Le même masquage, sur une structure (ce qui part vers les traces)."""
    if profondeur > 8:
        return "[structure trop profonde masquée]"
    if isinstance(valeur, str):
        return masquer(valeur)
    if isinstance(valeur, dict):
        return {k: ("***" if _CLE_SECRETE.fullmatch(str(k)) else masquer_arbre(v, profondeur + 1))
                for k, v in valeur.items()}
    if isinstance(valeur, (list, tuple)):
        rendu = [masquer_arbre(v, profondeur + 1) for v in valeur]
        return type(valeur)(rendu) if isinstance(valeur, tuple) else rendu
    return valeur


class FiltreSecrets(logging.Filter):
    """Masque toute valeur qui ressemble à une clé : message, arguments ET trace.

    On réécrit `msg` et `args` plutôt que le message formaté : le formatage n'a
    pas encore eu lieu quand le filtre passe, et une clé arrivée par `%s`
    échapperait à un filtre qui ne regarderait que `msg`. L'exception, elle, est
    formatée ici une fois pour toutes (`exc_text`) : le formateur reprend ce
    texte au lieu de refaire le sien.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.msg, str):
                record.msg = masquer(record.msg)
            elif record.msg is not None:
                texte = str(record.msg)
                masque = masquer(texte)
                if masque != texte:
                    record.msg = masque
            if record.args:
                record.args = masquer_arbre(record.args)
                # LE PIÈGE DU MESSAGE COUPÉ EN DEUX : `logger.info("…key=%s", cle)`
                # ne porte le secret NI dans le message (« key=%s ») NI dans
                # l'argument (la valeur seule, sans son nom). Il n'apparaît qu'une
                # fois les deux réunis. On masque donc aussi le message FORMATÉ ;
                # s'il change, il remplace le couple (message, arguments).
                try:
                    formate = record.getMessage()
                except Exception:  # noqa: BLE001 — arguments mal appariés : rien à formater
                    formate = None
                if formate:
                    masque = masquer(formate)
                    if masque != formate:
                        record.msg, record.args = masque, ()
            if record.exc_info and not record.exc_text:
                import traceback
                record.exc_text = masquer("".join(traceback.format_exception(*record.exc_info)).rstrip())
            elif record.exc_text:
                record.exc_text = masquer(record.exc_text)
            if getattr(record, "stack_info", None):
                record.stack_info = masquer(str(record.stack_info))
        except Exception:  # noqa: BLE001 — un journal ne fait jamais tomber l'app
            pass
        return True


_FILTRE = FiltreSecrets()


def poser_filtre(logger: logging.Logger | None = None) -> None:
    """Pose le filtre sur les HANDLERS (c'est par eux que tout passe) et sur les
    loggers connus. À rappeler après le démarrage du serveur : uvicorn installe
    ses propres handlers APRÈS l'import de ce module."""
    vus = set()

    def _poser_sur(obj):
        if id(obj) in vus:
            return
        vus.add(id(obj))
        if _FILTRE not in obj.filters:
            obj.addFilter(_FILTRE)

    racine = logger or logging.getLogger()
    _poser_sur(racine)
    for handler in list(racine.handlers):
        _poser_sur(handler)
    for nom in list(logging.root.manager.loggerDict):
        objet = logging.getLogger(nom)
        _poser_sur(objet)
        for handler in list(getattr(objet, "handlers", [])):
            _poser_sur(handler)

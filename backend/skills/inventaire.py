"""
Skill `inventaire_dossier` — ouvrir CHAQUE fichier d'un dossier, un par un, et
en rendre une liste neuve (Excel + tableau), avec la démarche sous les yeux.

Demande de Noa du 08/09 : « lister les fichiers du Drive en les ouvrant un
par un et produire une nouvelle liste, avec le détail de la démarche dans le
chat ».

POURQUOI UN SKILL ET PAS UNE BOUCLE DU MODÈLE. Ouvrir quarante fichiers, c'est
quarante gestes ; confiés au modèle, ils coûtent quarante appels, s'arrêtent
au budget d'actions, et la liste finale est une recopie qui s'arrête quelque
part (leçon du classeur de 95 lignes du 03/09). Ici le serveur liste, ouvre
(quatre de front, borné), décrit chaque fichier en une phrase avec le modèle
léger, écrit l'Excel par l'atelier et rend DEUX blocs garantis : la carte du
fichier et la liste de la démarche — ce qui a été listé, ouvert, lu, ce qui
n'a pas pu l'être et pourquoi. Le modèle ne recopie rien.

Le stockage vient de `classement.source` (Drive chez l'un, NAS chez l'autre) :
`fichiers_du_dossier` et `lire_fichier`. Rien n'est déposé ni modifié sur le
stockage ; les fichiers sont LUS, jamais rangés dans l'atelier (quarante
cartes seraient du bruit) — seul l'inventaire produit l'est.
"""
from __future__ import annotations

import asyncio
import logging
import posixpath

from skills.erreurs import SkillError
from skills.registre import Declaration

logger = logging.getLogger("symbiose.skills.inventaire")

MAX_INVENTAIRE = 60      # fichiers ouverts par appel (le compte total est dit)
DE_FRONT = 4             # lectures menées ensemble
EXTRAIT = 5000           # caractères lus par fichier pour le décrire
CONSIGNE_DESCRIPTION = (
    "Tu décris un document d'entreprise en UNE phrase de 25 mots au plus, en français : "
    "sa nature (devis, facture, plan, CCTP, courrier, photo…), pour qui ou quel chantier, "
    "et la date ou la référence si elles y sont. Rien d'autre que la phrase, aucune "
    "invention : si le texte ne dit pas, n'écris pas.")


def _taille(octets: int) -> str:
    if not octets:
        return ""
    if octets >= 1024 ** 2:
        return f"{octets / 1024 ** 2:.1f} Mo"
    if octets >= 1024:
        return f"{octets / 1024:.0f} Ko"
    return f"{octets} o"


def _extension(nom: str, mime: str = "") -> str:
    if mime.startswith("application/vnd.google-apps."):
        return {"document": "gdoc", "spreadsheet": "gsheet", "presentation": "gslides"}.get(
            mime.rsplit(".", 1)[-1], "google")
    return nom.rsplit(".", 1)[-1].lower() if "." in nom else ""


def description_de_secours(texte: str) -> str:
    """Sans modèle : les premiers mots lisibles du document."""
    mots = " ".join((texte or "").split())
    return (mots[:160] + "…") if len(mots) > 160 else mots


async def decrire(texte: str) -> str:
    """Une phrase par le modèle léger ; les premiers mots si le modèle manque."""
    if not (texte or "").strip():
        return ""
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        from llm.router import LLMTier, get_llm
        reponse = await get_llm(LLMTier.LIGHT).ainvoke(
            [SystemMessage(content=CONSIGNE_DESCRIPTION),
             HumanMessage(content=texte[:EXTRAIT])])
        phrase = " ".join(str(getattr(reponse, "content", "") or "").split())
        return phrase[:300] if phrase else description_de_secours(texte)
    except Exception as e:  # noqa: BLE001 — sans modèle, l'inventaire se fait quand même
        logger.info("Inventaire : description sans modèle (%s)", str(e)[:80])
        return description_de_secours(texte)


async def inventaire_dossier(data: dict, user) -> dict:
    dossier = str(data.get("dossier") or data.get("chemin") or data.get("nom") or "").strip()
    if not dossier:
        raise SkillError("Donne le dossier à inventorier (son nom ou son chemin).")
    try:
        limite = max(1, min(int(data.get("limite") or MAX_INVENTAIRE), MAX_INVENTAIRE))
    except (TypeError, ValueError):
        limite = MAX_INVENTAIRE
    decrire_chaque = str(data.get("resume", "true")).strip().lower() not in ("false", "0", "non")
    try:
        from classement.source import NOM_STOCKAGE, fichiers_du_dossier, lire_fichier
    except ImportError as e:
        raise SkillError("L'inventaire n'est pas branché sur le stockage de ce client.") from e

    chemin, fichiers = await fichiers_du_dossier(dossier, user)
    demarche = [f"Dossier « {chemin} » listé sur le {NOM_STOCKAGE} : {len(fichiers)} fichier(s)."]
    if not fichiers:
        return {"dossier": chemin, "nombre": 0, "demarche": demarche,
                "message_final": f"Le dossier « {chemin} » ne contient aucun fichier.",
                "a_faire": "Dis-le en une phrase, et propose un autre dossier."}
    cibles = fichiers[:limite]
    if len(fichiers) > limite:
        demarche.append(f"{limite} fichiers ouverts au plus par appel : les {len(fichiers) - limite} "
                        "suivants attendent un second appel (paramètre `limite`, ou `page`).")

    sem = asyncio.Semaphore(DE_FRONT)

    async def _un(f: dict) -> dict:
        async with sem:
            try:
                lu = await lire_fichier(f["ref"], user)
            except Exception as e:  # noqa: BLE001 — un fichier illisible n'arrête pas les autres
                # La RAISON est pour la personne : un refus ou une limite du
                # stockage se dit tel quel ; une faute de PROGRAMME se journalise
                # (09/09 : « module 'outils.drive' has no attribute … » lu dans le
                # chat, onze fois de suite).
                if isinstance(e, (AttributeError, TypeError, KeyError, NameError,
                                  IndexError, ImportError, AssertionError)):
                    logger.warning("Inventaire : lecture de « %s » impossible : %s", f.get("nom"), e)
                    raison = "lecture impossible (incident technique, journalisé)"
                else:
                    raison = str(e)[:120]
                return {**f, "etat": "illisible", "raison": raison, "texte": ""}
            # La source rend {texte, methode} depuis le 09/09 (lecture par
            # type, images décrites par la vision) ; une chaîne nue reste
            # acceptée. La MÉTHODE est dite : « lu — description par la
            # vision » n'est pas « lu — texte du PDF ».
            if isinstance(lu, dict):
                texte, methode = str(lu.get("texte") or ""), str(lu.get("methode") or "")
            else:
                texte, methode = str(lu or ""), ""
            if not texte.strip():
                return {**f, "etat": "sans texte lisible", "methode": methode, "texte": ""}
            return {**f, "etat": "lu", "methode": methode, "texte": texte[:EXTRAIT]}

    lus = await asyncio.gather(*[_un(f) for f in cibles])
    for l in lus:
        demarche.append(f"Ouvert « {l['nom']} » : {l['etat']}"
                        + (f" ({len(l['texte'])} caractères"
                           + (f", {l['methode']}" if l.get("methode") else "") + ")"
                           if l["etat"] == "lu" else "")
                        + (f" — {l['raison']}" if l.get("raison") else "") + ".")
    if decrire_chaque:
        descriptions = await asyncio.gather(*[decrire(l["texte"]) for l in lus])
        demarche.append(f"{sum(1 for d in descriptions if d)} fichier(s) décrit(s) en une phrase.")
    else:
        descriptions = [description_de_secours(l["texte"]) for l in lus]

    lignes = []
    for l, d in zip(lus, descriptions):
        lecture = l["etat"] + (f" — {l['methode']}" if l["etat"] == "lu" and l.get("methode") else "")
        lignes.append([l["nom"], _extension(l["nom"] or "", l.get("type") or ""),
                       _taille(int(l.get("octets") or 0)), lecture, d or ""])

    blocs: list = []
    bloc_fichier = None
    try:
        from bureautique.atelier import ajouter, ouvrir, terminer
        proprio = str(getattr(user, "id", "") or "")
        entete = {"titre": f"Inventaire — {posixpath.basename(chemin.rstrip('/')) or chemin}", "format": "xlsx"}
        elements = [{"type": "feuille", "nom": "Inventaire",
                     "entetes": ["Fichier", "Type", "Taille", "Lecture", "Description"],
                     "lignes": lignes}]

        def _produire():
            jeton = ouvrir(entete, proprio)
            ajouter(jeton, elements, proprio)
            return jeton, terminer(jeton, proprio)

        jeton, fiche = await asyncio.to_thread(_produire)
        bloc_fichier = {"type": "fichier", "url": f"/api/documents/{jeton}", "nom": "inventaire.xlsx",
                        "titre": entete["titre"], "format": "xlsx", "octets": fiche.get("octets")}
        blocs.append(bloc_fichier)
        demarche.append("Inventaire écrit dans un classeur Excel (une ligne par fichier).")
    except Exception as e:  # noqa: BLE001 — sans atelier, le tableau reste
        logger.warning("Inventaire : Excel non produit (%s)", str(e)[:120])
        demarche.append("Le classeur Excel n'a pas pu être produit : le tableau ci-dessous en tient lieu.")
        blocs.append({"type": "table", "titre": entete_titre(chemin),
                      "columns": ["Fichier", "Type", "Taille", "Lecture", "Description"],
                      "rows": lignes})
    blocs.append({"type": "list", "titre": "Démarche suivie", "items": demarche})

    illisibles = [l["nom"] for l in lus if l["etat"] != "lu"]
    return {
        "dossier": chemin, "nombre": len(fichiers), "ouverts": len(cibles),
        "lus": sum(1 for l in lus if l["etat"] == "lu"), "illisibles": illisibles,
        "lignes": [{"nom": l[0], "lecture": l[3], "description": l[4]} for l in lignes],
        "demarche": demarche,
        "bloc_ui": blocs, "bloc_garanti": True,
        "message_final": (f"{len(cibles)} fichier(s) ouvert(s) sur {len(fichiers)} dans « {chemin} », "
                          f"{sum(1 for l in lus if l['etat'] == 'lu')} lu(s)"
                          + (f", {len(illisibles)} non lisible(s)" if illisibles else "") + "."),
        "a_faire": ("L'inventaire (fichier) et la démarche sont DÉJÀ affichés : ne recopie ni la "
                    "liste ni les étapes. Dis en deux phrases ce que le dossier contient d'après les "
                    "descriptions, et ce qui n'a pas pu être lu. S'il reste des fichiers non "
                    "ouverts, propose de continuer. Ce classeur est la LISTE DES FICHIERS du "
                    "dossier (une ligne par fichier, avec sa description) et rien d'autre : ne le "
                    "présente jamais comme un quantitatif, un chiffrage ou un devis, et ne le "
                    "compte pas parmi les livrables d'une demande qui ne le réclamait pas."),
    }


def entete_titre(chemin: str) -> str:
    return f"Inventaire — {posixpath.basename(chemin.rstrip('/')) or chemin}"


SKILLS = {
    "inventaire_dossier": Declaration(
        fonction=inventaire_dossier,
        description=(
            "INVENTORIE un dossier du stockage en OUVRANT chaque fichier un par un : liste les "
            "fichiers, lit chacun, le décrit en une phrase, produit un classeur Excel "
            "(fichier, type, taille, lecture, description) et affiche la DÉMARCHE (ce qui a été "
            "listé, ouvert, lu, ce qui n'a pas pu l'être). `dossier` : nom ou chemin ; `limite` "
            "(60 au plus par appel) ; `resume: false` pour ne pas décrire. À appeler sur "
            "« liste-moi ce dossier en ouvrant chaque fichier », « fais l'inventaire de », "
            "« qu'y a-t-il vraiment dans ». Ne modifie rien sur le stockage."),
        requis=["dossier"], optionnels=["limite", "resume"],
        effet="lecture", libelle="j'inventorie le dossier fichier par fichier"),
}

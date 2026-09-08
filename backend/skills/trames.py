"""
LES TRAMES — ce que la maison reprend à chaque fois.

Demande de Noa (02/09) : « il doit être capable d'enregistrer des trames qu'il
reprend à chaque fois, que ce soit pour des documents, logo, méthodes,
process ».

TROIS GENRES, UNE SEULE PORTE. Un devis type (.docx avec son logo et sa trame
de tableau), un logo (l'image elle-même), une méthode (du texte : la marche à
suivre pour monter un dossier d'appel d'offres). Les trois se demandent de la
même façon — « reprends la trame du devis » — et c'est ce qui compte à
l'usage ; leur nature les sépare seulement au moment de s'en servir.

CE QU'UNE TRAME N'EST PAS. Ce n'est pas une consigne : une consigne (021) est
une phrase injectée dans CHAQUE prompt, qui change le comportement du modèle.
Une trame est un objet qu'on rouvre. Les confondre reviendrait à glisser un
fichier de 300 ko dans chaque tour, ou à laisser un modèle réécrire un document
type — et il finirait par le faire.

LE CHOIX QUI MÉRITE D'ÊTRE DÉFENDU : effet `ecriture_interne`, pas `externe`.
Enregistrer ou reprendre une trame ne produit rien hors de l'entreprise, et la
règle du projet réserve l'accord humain aux effets qui SORTENT. Le document
rempli reste dans l'application, téléchargeable ; l'envoyer à un client passe,
lui, par `envoyer_email` et sa validation. Exiger un accord ici irait contre
« une lecture se fait, on ne demande pas » et contre la demande de Noa de
cesser de multiplier les confirmations.

ON NE DEVINE JAMAIS LAQUELLE. Comme pour les tâches, une désignation qui vise
plusieurs trames n'en prend AUCUNE : elle les liste et redemande. C'est ce qui
empêche « reprends la trame du devis » de choisir au hasard entre « devis
terrasse » et « devis élagage ».
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from database.connection import get_db

logger = logging.getLogger("duret.trames")

# Une trame reste une trame, pas un dépôt de fichiers.
MAX_OCTETS = 12 * 1024 * 1024
MAX_TRAMES = 200
# Ce qu'on montre du texte d'une méthode dans une liste : de quoi la
# reconnaître, pas de quoi la lire en entier.
EXTRAIT = 300

# CE QU'ON MONTRE DE LA STRUCTURE D'UN DOCUMENT qu'on s'apprête à reproduire.
# Le modèle doit voir assez de texte pour désigner ce qu'il veut remplacer, et
# pas au point de noyer le tour : un CCTP de 80 pages tient en dizaines de
# milliers de caractères, et un résultat de skill est tranché bien avant.
MAX_TEXTES_MONTRES = 120
MAX_CARACTERES_STRUCTURE = 6000


class TrameInvalide(Exception):
    """Refus explicite : la demande ne peut pas aboutir, et on dit pourquoi."""


def _extrait(texte: str, taille: int = EXTRAIT) -> str:
    t = (texte or "").strip()
    return t if len(t) <= taille else t[:taille].rstrip() + "…"


async def _trouver(designation: str) -> list[dict]:
    """Les trames que cette désignation vise. Vide, une, ou plusieurs."""
    motif = (designation or "").strip()
    if not motif:
        return []
    async with get_db() as conn:
        exact = await conn.fetch(
            "SELECT * FROM trames WHERE actif AND lower(nom) = lower($1)", motif)
        if exact:
            return [dict(r) for r in exact]
        return [dict(r) for r in await conn.fetch(
            "SELECT * FROM trames WHERE actif AND nom ILIKE $1 ORDER BY nom", f"%{motif}%")]


def _ambigu(candidates: list[dict], designation: str) -> dict:
    """Plusieurs trames visées : on n'en prend AUCUNE."""
    return {
        "ambigu": True,
        "candidates": [{"nom": c["nom"], "genre": c["genre"],
                        "description": c["description"]} for c in candidates],
        "message": (f"Plusieurs trames correspondent à « {designation} ». "
                    "Précisez laquelle."),
        "a_faire": ("Montre les trames trouvées et demande LAQUELLE. Ne choisis "
                    "PAS à sa place : reprendre la mauvaise trame produit un "
                    "document faux qui a l'air juste."),
    }


# ── Enregistrer ──────────────────────────────────────────────────────────

async def enregistrer_trame(parametres: dict, utilisateur) -> dict:
    """Retient un document, un logo ou une méthode pour le reprendre ensuite."""
    from bureautique import trame as moteur

    nom = str(parametres.get("nom") or "").strip()
    if not nom:
        raise TrameInvalide("Donnez un nom à la trame : c'est par lui qu'on la "
                            "redemandera.")
    genre = str(parametres.get("genre") or "").strip().lower() or "document"
    if genre not in ("document", "logo", "methode"):
        raise TrameInvalide("Genre attendu : « document », « logo » ou « methode ».")

    texte = str(parametres.get("texte") or "").strip()
    description = str(parametres.get("description") or "").strip()
    reference = str(parametres.get("fichier") or "").strip()

    octets: Optional[bytes] = None
    type_fichier = nom_fichier = None
    variables: list = []
    apercu: dict = {}

    if genre in ("document", "logo"):
        if not reference:
            raise TrameInvalide(
                "Indiquez le fichier à retenir, par la référence qu'un geste "
                "précédent vous a rendue (une pièce jointe ouverte, un document "
                "produit, un fichier du Drive).")
        # LE MODÈLE NE DÉSIGNE QUE CE QU'UN GESTE LUI A RENDU — jamais un
        # chemin qu'il compose. Même règle que pour les pièces jointes d'un
        # envoi (`mail/attaches.py`) : c'est ce qui empêche de faire lire au
        # serveur un fichier que personne ne lui a montré.
        from mail.attaches import resoudre

        boite = str(getattr(utilisateur, "email", "") or "").lower()
        pretes, refusees = await resoudre([reference], utilisateur, boite)
        if not pretes:
            pourquoi = (refusees[0].get("raison") if refusees
                        else "cette référence ne correspond à aucun fichier connu")
            raise TrameInvalide(
                f"Je ne retrouve pas « {reference} » : {pourquoi}. Ouvrez "
                "d'abord le fichier (pièce jointe, document produit ou fichier "
                "du Drive), puis reprenez la référence qui vous est rendue.")
        piece = pretes[0]
        octets, nom_fichier = piece["octets"], piece["nom"]
        if len(octets) > MAX_OCTETS:
            raise TrameInvalide(
                f"Ce fichier fait {len(octets) // 1024} ko, au-delà des "
                f"{MAX_OCTETS // (1024 * 1024)} Mo admis pour une trame.")

        if genre == "document":
            type_fichier = moteur.type_de(nom_fichier or "", piece.get("mime") or "")
            if not type_fichier:
                raise TrameInvalide(
                    "Seuls les fichiers Word (.docx) et Excel (.xlsx) peuvent "
                    "servir de trame à remplir : ce sont les seuls qu'on sache "
                    "rouvrir sans rien perdre de leur mise en page. Un PDF se "
                    "garde comme pièce, pas comme trame.")
            apercu = moteur.analyser(octets, type_fichier)
            ok, pourquoi = moteur.exploitable(apercu)
            if not ok:
                raise TrameInvalide(pourquoi)
            variables = apercu.get("variables") or []
            # Le texte du document ne part PAS en base : il est déjà dans les
            # octets, et le stocker deux fois ferait diverger les deux copies.
            apercu = {k: v for k, v in apercu.items() if k != "textes"}
        else:
            type_fichier = (nom_fichier or "").rsplit(".", 1)[-1].lower() or "png"
    else:
        if not texte:
            raise TrameInvalide("Une méthode, c'est du texte : dites la marche "
                                "à suivre.")

    async with get_db() as conn:
        combien = await conn.fetchval("SELECT count(*) FROM trames WHERE actif")
        if (combien or 0) >= MAX_TRAMES:
            raise TrameInvalide(
                f"Il y a déjà {combien} trames. Retirez-en une avant d'en "
                "ajouter (une trame qu'on ne retrouve plus ne sert personne).")
        # Le nom fait foi : réenregistrer sous le même nom REMPLACE, plutôt que
        # de créer un doublon que personne ne saurait départager.
        await conn.execute(
            """INSERT INTO trames (nom, genre, type_fichier, nom_fichier, contenu,
                                   texte, description, variables, apercu, octets,
                                   cree_par)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9::jsonb, $10, $11::uuid)
               ON CONFLICT (lower(nom)) WHERE actif DO UPDATE SET
                   genre = EXCLUDED.genre, type_fichier = EXCLUDED.type_fichier,
                   nom_fichier = EXCLUDED.nom_fichier, contenu = EXCLUDED.contenu,
                   texte = EXCLUDED.texte, description = EXCLUDED.description,
                   variables = EXCLUDED.variables, apercu = EXCLUDED.apercu,
                   octets = EXCLUDED.octets, derniere_maj = NOW()""",
            nom, genre, type_fichier, nom_fichier, octets, texte, description,
            json.dumps(variables), json.dumps(apercu), len(octets or b""),
            str(getattr(utilisateur, "id", "")) or None)

    quoi = {"document": "Le document", "logo": "Le logo",
            "methode": "La méthode"}[genre]
    detail = ""
    if variables:
        detail = (" Les valeurs à fournir à chaque reprise : "
                  + ", ".join(variables) + ".")
    return {
        "enregistree": True, "nom": nom, "genre": genre,
        "variables": variables,
        "message_final": (f"{quoi} « {nom} » est retenu. Il suffira de le "
                          f"demander par son nom.{detail}"),
        "a_faire": "Dis en une phrase que la trame est retenue, et sous quel nom.",
    }


# ── Lister ───────────────────────────────────────────────────────────────

async def mes_trames(parametres: dict, utilisateur) -> dict:
    """Ce que la maison a retenu."""
    genre = str(parametres.get("genre") or "").strip().lower()
    async with get_db() as conn:
        if genre in ("document", "logo", "methode"):
            lignes = await conn.fetch(
                """SELECT nom, genre, type_fichier, description, texte, variables,
                          octets, usages, derniere_maj
                   FROM trames WHERE actif AND genre = $1 ORDER BY nom""", genre)
        else:
            lignes = await conn.fetch(
                """SELECT nom, genre, type_fichier, description, texte, variables,
                          octets, usages, derniere_maj
                   FROM trames WHERE actif ORDER BY genre, nom""")

    liste = [dict(r) for r in lignes]
    if not liste:
        return {"nombre": 0,
                "message_final": "Aucune trame n'est enregistrée pour l'instant.",
                "a_faire": ("Dis qu'il n'y en a pas encore, et propose d'en "
                            "retenir une à partir d'un document existant.")}

    corps = []
    for t in liste:
        v = t["variables"]
        if isinstance(v, str):
            v = json.loads(v or "[]")
        corps.append([
            t["nom"],
            {"document": "document", "logo": "logo", "methode": "méthode"}[t["genre"]],
            t["description"] or _extrait(t["texte"], 80) or "—",
            ", ".join(v) if v else "—",
            str(t["usages"]),
        ])
    return {
        "nombre": len(liste),
        "trames": [{"nom": t["nom"], "genre": t["genre"],
                    "description": t["description"]} for t in liste],
        # LE TABLEAU S'AFFICHE MÉCANIQUEMENT : leçon de `fd1bcf7` — un bloc qui
        # DOIT paraître à l'écran se construit ici, pas en demandant au modèle
        # de le recopier.
        "bloc_garanti": True,
        "bloc_ui": {"type": "table", "titre": "Les trames enregistrées",
                    "columns": ["Nom", "Genre", "À quoi elle sert",
                                "Valeurs à fournir", "Reprises"],
                    "lignes": corps},
        "message_final": f"{len(liste)} trame(s) enregistrée(s).",
        "a_faire": ("Le tableau s'affiche AUTOMATIQUEMENT : n'écris aucun bloc, "
                    "ne recopie pas les lignes. Dis en une phrase combien il y "
                    "en a, et propose d'en reprendre une."),
    }


# ── Reprendre ────────────────────────────────────────────────────────────

async def utiliser_trame(parametres: dict, utilisateur) -> dict:
    """Rouvre la trame et la remplit : le document d'origine, autre contenu."""
    from bureautique import atelier, trame as moteur

    designation = str(parametres.get("trame") or "").strip()
    candidates = await _trouver(designation)
    if not candidates:
        raise TrameInvalide(
            f"Aucune trame ne correspond à « {designation} ». Demandez la liste "
            "des trames pour voir ce qui est enregistré.")
    if len(candidates) > 1:
        return _ambigu(candidates, designation)

    t = candidates[0]
    if t["genre"] == "methode":
        # Une méthode ne se remplit pas : elle se lit. La rendre telle quelle
        # est exactement ce qu'on attend d'elle.
        return {"nom": t["nom"], "genre": "methode", "texte": t["texte"],
                "message_final": f"Voici la méthode « {t['nom']} ».",
                "a_faire": ("Applique cette méthode à la demande en cours. Ne la "
                            "recopie pas telle quelle : suis-la.")}

    if t["genre"] == "logo" or not t["contenu"]:
        raise TrameInvalide(
            f"« {t['nom']} » est un {t['genre']} : il se joint, il ne se remplit "
            "pas. Demandez-le en pièce jointe d'un envoi ou d'un document.")

    remplacements = parametres.get("remplacements") or {}
    if isinstance(remplacements, str):
        try:
            remplacements = json.loads(remplacements)
        except ValueError:
            raise TrameInvalide("Les remplacements doivent être une table "
                                "« texte cherché » → « texte à mettre ».")
    if not isinstance(remplacements, dict) or not remplacements:
        variables = t["variables"]
        if isinstance(variables, str):
            variables = json.loads(variables or "[]")
        manque = (" Les valeurs attendues : " + ", ".join(variables) + "."
                  if variables else "")
        raise TrameInvalide(
            f"Dites ce qu'il faut remplacer dans « {t['nom']} ».{manque}")

    octets, faits = moteur.remplir(bytes(t["contenu"]), t["type_fichier"],
                                   remplacements)
    base = (t["nom"] or "document").replace("/", "-")
    nom_sortie = f"{base}.{t['type_fichier']}"
    jeton = atelier.deposer_fichier(
        nom_sortie, octets, str(getattr(utilisateur, "id", "")), origine="trame")

    async with get_db() as conn:
        await conn.execute(
            "UPDATE trames SET usages = usages + 1 WHERE lower(nom) = lower($1)",
            t["nom"])

    if faits == 0:
        # RIEN N'A CHANGÉ, ET ON LE DIT. Rendre un document identique à
        # l'original sans le signaler ferait croire au travail fait — c'est
        # exactement le genre de silence qui part chez un client.
        message = (f"Aucun des textes cherchés n'a été trouvé dans « {t['nom']} ». "
                   "Le document est rendu tel quel : vérifiez l'orthographe "
                   "exacte de ce qu'il fallait remplacer.")
    else:
        message = (f"« {t['nom']} » est repris avec {faits} remplacement(s). "
                   "La mise en page, le logo et les styles d'origine sont "
                   "conservés : c'est le fichier lui-même, pas une copie "
                   "reconstruite.")
    return {
        "nom": t["nom"], "remplacements": faits, "fichier": nom_sortie,
        "bloc_garanti": True,
        "bloc_ui": {"type": "fichier", "nom": nom_sortie,
                    "url": f"/api/documents/{jeton}",
                    "titre": f"{t['nom']} (repris)"},
        "message_final": message,
        "a_faire": ("La carte du fichier s'affiche AUTOMATIQUEMENT : n'écris "
                    "aucun bloc. Dis en une phrase ce qui a été repris et ce "
                    "qui a été remplacé."),
    }


# ── Reproduire : le document d'un autre, avec notre contenu ──────────────

async def reproduire_document(parametres: dict, utilisateur) -> dict:
    """Rouvre un document du serveur et n'en change que le texte.

    DEMANDE DE NOA (08/09) : « il doit être capable de recréer des documents
    sur la base de la structure visuelle d'un document de leur Drive ».

    POURQUOI CE GESTE EXISTE À CÔTÉ DES TRAMES. `enregistrer_trame` puis
    `utiliser_trame` savaient déjà le faire, mais au prix d'un ENREGISTREMENT :
    le document entrait en base, sous un nom, pour toujours, et comptait dans
    le plafond des trames. Or reprendre la présentation d'un devis qu'on vient
    de trouver dans un dossier est un geste de tous les jours, pas une décision
    de bibliothèque. On sépare donc les deux : ici, on reproduit une fois ; là,
    on retient ce qu'on reprendra toujours. Le moteur est le MÊME
    (`bureautique/trame.py`), donc la garantie est la même — on n'écrit pas le
    document, on ouvre l'original et on n'en change que le texte : styles,
    logo, en-têtes, largeurs de colonnes et formules restent par construction.

    DEUX TEMPS, ET C'EST VOULU. Sans `remplacements`, le geste RÉPOND par la
    structure : paragraphes, tableaux, textes présents, variables reconnues.
    Le modèle ne peut pas remplacer à l'aveugle ce qu'il n'a pas lu, et deviner
    « ce qui ressemble à un nom de client » détruirait « rue Dupont ». Avec
    `remplacements`, il produit le document. Le second appel n'est pas un
    rejeu : il porte une table que le premier a rendue possible.
    """
    from bureautique import atelier, trame as moteur

    reference = str(parametres.get("fichier") or parametres.get("chemin")
                    or parametres.get("document") or "").strip()
    if not reference:
        raise TrameInvalide(
            "Indiquez le document à reproduire, par la référence qu'un geste "
            "précédent vous a rendue : le `chemin` exact d'un fichier listé sur "
            "le serveur, une pièce jointe ouverte, ou un document produit ici.")

    # LE MODÈLE NE DÉSIGNE QUE CE QU'UN GESTE LUI A RENDU — même règle que
    # `enregistrer_trame` et les pièces jointes d'un envoi : c'est elle qui
    # empêche de faire ouvrir au serveur un fichier que personne ne lui a
    # montré, et le périmètre du serveur de fichiers s'applique en dessous.
    from mail.attaches import resoudre

    boite = str(getattr(utilisateur, "email", "") or "").lower()
    pretes, refusees = await resoudre([reference], utilisateur, boite)
    if not pretes:
        pourquoi = (refusees[0].get("raison") if refusees
                    else "cette référence ne correspond à aucun fichier connu")
        raise TrameInvalide(
            f"Je ne retrouve pas « {reference} » : {pourquoi}. Listez le dossier "
            "(le geste de listage du serveur) et reprenez le `chemin` EXACT "
            "d'une entrée, puis redemandez.")

    piece = pretes[0]
    octets, nom_fichier = piece["octets"], piece["nom"]
    if len(octets) > MAX_OCTETS:
        raise TrameInvalide(
            f"Ce fichier fait {len(octets) // 1024} ko, au-delà des "
            f"{MAX_OCTETS // (1024 * 1024)} Mo qu'on sait rouvrir.")

    genre = moteur.type_de(nom_fichier or "", piece.get("mime") or "")
    if not genre:
        raise TrameInvalide(
            "Seuls les fichiers Word (.docx) et Excel (.xlsx) se reproduisent "
            "sans rien perdre de leur mise en page : ce sont les seuls qu'on "
            "sache rouvrir. Un PDF ne se rouvre pas — il faudrait le "
            "reconstruire, donc perdre ce qu'on cherche justement à garder.")

    try:
        analyse = moteur.analyser(octets, genre)
    except Exception as e:  # noqa: BLE001 — un fichier abîmé se DIT
        raise TrameInvalide(
            f"Ce document n'a pas pu être ouvert : {str(e)[:160]}") from e
    bon, pourquoi = moteur.exploitable(analyse)
    if not bon:
        raise TrameInvalide(pourquoi)

    remplacements = parametres.get("remplacements") or {}
    if isinstance(remplacements, str):
        try:
            remplacements = json.loads(remplacements)
        except ValueError:
            raise TrameInvalide("Les remplacements doivent être une table "
                                "« texte cherché » → « texte à mettre ».")

    # ── Premier temps : la structure, pour savoir quoi remplacer ──
    if not isinstance(remplacements, dict) or not remplacements:
        textes, total = [], 0
        for t in (analyse.get("textes") or []):
            if len(textes) >= MAX_TEXTES_MONTRES or total >= MAX_CARACTERES_STRUCTURE:
                break
            textes.append(t)
            total += len(t)
        coupe = len(analyse.get("textes") or []) > len(textes)
        structure = {"nom": nom_fichier, "type": genre,
                     "variables": analyse.get("variables") or []}
        if genre == "docx":
            structure.update({"paragraphes": analyse.get("paragraphes"),
                              "tableaux": analyse.get("tableaux"),
                              "images": analyse.get("images"),
                              "entete": analyse.get("entete")})
        else:
            structure["feuilles"] = analyse.get("feuilles")
        return {
            "fichier": nom_fichier, "structure": structure, "textes": textes,
            "textes_coupes": coupe or None,
            "message_final": (
                f"« {nom_fichier} » est ouvert : sa présentation est prête à être "
                "reprise. Dites ce qu'il faut y changer."),
            "a_faire": (
                "Le document n'est PAS encore produit : ce tour rend sa STRUCTURE. "
                "Rappelle CE MÊME geste avec `remplacements` — une table « texte "
                "exactement présent ci-dessus » vers « texte à mettre ». Prends les "
                "textes cherchés dans la liste rendue, JAMAIS de mémoire : un texte "
                "approché ne remplace rien. "
                + (f"Ce document porte des variables ({', '.join(structure['variables'][:12])}) : "
                   "remplace-les en priorité. " if structure["variables"] else
                   "Ce document ne porte aucune variable entre accolades : remplace "
                   "les valeurs réelles (nom du client, référence, dates, montants). ")
                + ("La liste des textes est COUPÉE : si ce qu'il faut changer n'y "
                   "figure pas, dis-le plutôt que de deviner. " if coupe else "")
                + "Montre à la personne ce que tu comptes remplacer avant de le faire."),
        }

    # ── Second temps : le document ──
    try:
        produits, faits = moteur.remplir(octets, genre, remplacements)
    except ValueError as e:
        raise TrameInvalide(str(e)) from e

    base = (nom_fichier or f"document.{genre}").rsplit(".", 1)[0]
    nom_sortie = f"{base} (repris).{genre}"
    jeton = atelier.deposer_fichier(
        nom_sortie, produits, str(getattr(utilisateur, "id", "")),
        origine="reproduction")

    if faits == 0:
        # RIEN N'A CHANGÉ, ET ON LE DIT — même règle que `utiliser_trame` :
        # rendre une copie conforme sans le signaler ferait croire au travail
        # fait, et c'est ce document-là qui part chez un client.
        message = (f"Aucun des textes cherchés n'a été trouvé dans "
                   f"« {nom_fichier} ». Le document est rendu tel quel : "
                   "reprenez l'orthographe exacte de ce qu'il fallait changer.")
    else:
        message = (f"« {nom_fichier} » est repris avec {faits} remplacement(s). "
                   "La mise en page, le logo, les styles et les formules d'origine "
                   "sont conservés : c'est le fichier lui-même, pas une copie "
                   "reconstruite.")
    return {
        "fichier": nom_sortie, "source": nom_fichier, "remplacements": faits,
        "bloc_garanti": True,
        "bloc_ui": {"type": "fichier", "nom": nom_sortie,
                    "url": f"/api/documents/{jeton}",
                    "titre": nom_sortie, "format": genre,
                    "octets": len(produits)},
        "message_final": message,
        "a_faire": ("La carte du document et son aperçu s'affichent "
                    "AUTOMATIQUEMENT : n'écris aucun bloc. Dis en une phrase ce "
                    "qui a été repris et ce qui a été remplacé. Si la personne "
                    "voudra le refaire souvent, propose de RETENIR ce document "
                    "comme trame."),
    }


# ── Oublier ──────────────────────────────────────────────────────────────

async def oublier_trame(parametres: dict, utilisateur) -> dict:
    """Retire une trame. Une désignation ambiguë n'en retire AUCUNE."""
    designation = str(parametres.get("trame") or "").strip()
    candidates = await _trouver(designation)
    if not candidates:
        raise TrameInvalide(f"Aucune trame ne correspond à « {designation} ».")
    if len(candidates) > 1:
        return _ambigu(candidates, designation)

    t = candidates[0]
    async with get_db() as conn:
        # On DÉSACTIVE plutôt que de supprimer : les octets d'un devis type
        # patiemment mis en forme ne se retrouvent pas, et un retrait par
        # erreur doit rester réparable en base.
        await conn.execute(
            "UPDATE trames SET actif = false, derniere_maj = NOW() WHERE id = $1",
            t["id"])
    return {
        "retiree": True, "nom": t["nom"],
        "message_final": (f"La trame « {t['nom']} » ne sera plus proposée. "
                          "Elle n'est pas détruite : elle peut être remise."),
        "a_faire": "Dis en une phrase que la trame est retirée.",
    }


# ── Le registre ──────────────────────────────────────────────────────────
#
# UN SEUL ENDROIT DE DÉCLARATION. `skills/registre.py` découvre ce dictionnaire
# tout seul : pas de `SKILLS_NATIFS`, pas de catalogue à tenir dans
# `protocol.py`, pas de libellé à poser dans `journal.py`. C'est exactement ce
# pour quoi le registre a été écrit, et c'est ce qui rend le projet
# duplicable — remplacer `skills/` suffit.
from skills.registre import Declaration  # noqa: E402

SKILLS = {
    "enregistrer_trame": Declaration(
        fonction=enregistrer_trame,
        description=(
            "RETIENT une trame que l'assistant reprendra a chaque fois : un "
            "document type (.docx ou .xlsx), un logo, ou une methode de travail. "
            "`nom` : le nom court par lequel on la redemandera (« devis type »). "
            "`genre` : « document », « logo » ou « methode ». `fichier` : pour un "
            "document ou un logo, la REFERENCE que t'a rendue un geste precedent "
            "(piece jointe ouverte, document produit, fichier du Drive) -- jamais "
            "un chemin que tu composes. `texte` : pour une methode, la marche a "
            "suivre. `description` : a quoi elle sert, en une phrase. Un document "
            "retenu garde SA mise en page, son logo et ses styles : le reprendre "
            "rouvre le fichier d'origine au lieu d'en fabriquer un nouveau. "
            "Reenregistrer sous le meme nom REMPLACE"),
        requis=["nom"], optionnels=["genre", "fichier", "texte", "description"],
        # Retenir une trame ne produit rien hors de l'entreprise : c'est de la
        # meme famille que `retenir` et `enregistrer_procedure`.
        effet="ecriture_interne",
        libelle="je retiens la trame"),
    "mes_trames": Declaration(
        fonction=mes_trames,
        description=(
            "LISTE les trames enregistrees : documents types, logos, methodes. "
            "`genre` (optionnel) pour n'en voir qu'une famille. A appeler avant "
            "de dire qu'une trame n'existe pas, et quand on demande « qu'est-ce "
            "que tu sais reprendre ? ». Le tableau s'affiche AUTOMATIQUEMENT"),
        requis=[], optionnels=["genre"],
        effet="lecture",
        libelle="je regarde les trames"),
    "utiliser_trame": Declaration(
        fonction=utiliser_trame,
        description=(
            "REPREND une trame. Pour un DOCUMENT : rouvre le fichier d'origine "
            "et n'en remplace que les textes indiques, en gardant la mise en "
            "page, le logo, les styles et les formules -- c'est le fichier "
            "lui-meme, pas une copie reconstruite. `trame` : son nom. "
            "`remplacements` : une table « texte cherche » vers « texte a "
            "mettre » ({\"Monsieur Dupont\": \"Madame Martin\"}). Pour une "
            "METHODE : rend la marche a suivre, que tu appliques. Si la "
            "designation vise plusieurs trames, RIEN n'est repris : demande "
            "laquelle"),
        requis=["trame"], optionnels=["remplacements"],
        effet="ecriture_interne",
        libelle="je reprends la trame"),
    "reproduire_document": Declaration(
        fonction=reproduire_document,
        description=(
            "RECREE un document Word ou Excel EN REPRENANT LA PRESENTATION d'un "
            "document existant : on rouvre le fichier d'origine et on n'en change "
            "que le texte, donc le logo, les styles, les en-tetes, les largeurs "
            "de colonnes et les formules sont conserves a l'identique. A utiliser "
            "des qu'on demande « refais ce devis pour un autre client », « meme "
            "presentation que ce document », « reprends la trame de ce fichier ». "
            "`fichier` : la REFERENCE rendue par un geste precedent -- le `chemin` "
            "EXACT d'un fichier liste sur le serveur, une piece jointe ouverte, ou "
            "un document produit ici ; jamais un chemin que tu composes. "
            "`remplacements` : la table « texte cherche » vers « texte a mettre ». "
            "SANS `remplacements`, ce geste rend la STRUCTURE du document (textes "
            "presents, variables) : appelle-le une premiere fois pour voir, puis "
            "une seconde avec la table. Le document produit s'affiche "
            "AUTOMATIQUEMENT, avec son apercu. Pour un document qu'on reprendra "
            "TOUJOURS, `enregistrer_trame` le retient une fois pour toutes"),
        requis=["fichier"], optionnels=["remplacements"],
        # Produit un document DANS l'application : rien ne sort de l'entreprise,
        # comme `utiliser_trame` et `produire_document`.
        effet="ecriture_interne",
        libelle="je reprends la presentation du document"),
    "oublier_trame": Declaration(
        fonction=oublier_trame,
        description=(
            "RETIRE une trame de celles que l'assistant propose. `trame` : son "
            "nom. Elle n'est pas detruite, elle peut etre remise. Si la "
            "designation vise plusieurs trames, RIEN n'est retire : demande "
            "laquelle"),
        requis=["trame"], optionnels=[],
        effet="ecriture_interne",
        libelle="je retire la trame"),
}

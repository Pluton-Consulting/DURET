"""
LES ROUTINES — ce qu'on demande dix fois par semaine, en UN SEUL appel.

POURQUOI CE MODULE EXISTE. « Sors-moi la liste des clients » se répondait
jusqu'ici en enchaînant `interroger_donnees` trois fois : une fois sans
argument pour découvrir les jeux de données, une fois avec `source_type` pour
voir les colonnes, une fois avec un filtre pour obtenir les lignes. Trois
allers-retours, donc trois passages complets dans la cascade LLM — et chacun
paie les fournisseurs en panne avant d'atteindre celui qui répond. Sur la
session du 21/08, cela faisait une minute et demie pour une question dont la
réponse tient dans une requête SQL.

Le remède n'est pas un meilleur prompt : c'est de rendre le geste ATOMIQUE.
Une question fréquente mérite un skill qui la répond d'un coup, avec le bloc
d'écran déjà prêt. Moins d'appels au modèle, c'est moins de latence ET moins
d'occasions de se tromper.

TROIS ROUTINES :
  · `liste_clients`  — qui sont les clients, combien, avec quoi les joindre ;
  · `fiche_client`   — TOUT ce qu'on sait d'un client : devis, montants,
                       chiffre d'affaires, chantiers, contact — d'un seul appel
                       et à travers TOUS les jeux de données importés ;
  · `check_mails`    — le point sur le courrier récent, prêt à être résumé.

ELLES NE SAVENT RIEN DU MÉTIER. Aucun nom de colonne n'est codé en dur : les
imports viennent de fichiers Excel ou CSV faits par le client, dont les
en-têtes varient (« Nom », « Client », « Raison sociale », « Société »…). Les
colonnes sont donc RECONNUES par famille de synonymes, et ce qui n'est pas
reconnu est rendu tel quel — mieux vaut afficher une colonne qu'on n'a pas su
nommer que de la perdre.
"""
from __future__ import annotations

import logging
import re
import unicodedata

logger = logging.getLogger("pluton.skills.routines")

MAX_CLIENTS = 5000
# CE QUI ENTRE DANS LE BLOC D'ÉCRAN. Relevé le 22/08 : le bloc portait 300
# lignes, le modèle a dû le recopier, s'est arrêté vers la quarantième et a
# écrit « 300 affichés ». Un bloc que le modèle doit retaper doit tenir dans ce
# qu'il retape sans faute : soixante noms, et une pagination par initiale pour
# la suite. Le TOTAL, lui, reste exact et se dit.
MAX_AFFICHES = 60
MAX_LIGNES_PAR_JEU = 40


# ── Reconnaissance des colonnes, par familles de synonymes ──────────────────
#
# L'ordre compte : le premier synonyme trouvé gagne. « raison_sociale » avant
# « nom » parce qu'un fichier qui porte les deux met l'identité dans le premier
# et le nom du contact dans le second.
FAMILLES = {
    # « client » en DERNIER : c'est souvent un drapeau ou un identifiant, pas
    # un nom. « nom » avant lui, mais après la raison sociale (un fichier qui
    # porte les deux met l'identité dans la première et le contact dans le
    # second).
    "nom": ("raison_sociale", "raison sociale", "societe", "société",
            "nom_client", "customer", "entreprise", "nom", "name", "client"),
    # Le prénom à part : quand l'export le sépare du nom, « DUPONT » seul n'est
    # qu'un bout du client (relevé le 22/08 : « elle n'a donné que les noms »).
    "prenom": ("prenom", "prénom", "first_name", "firstname", "first name"),
    "email": ("email", "e-mail", "mail", "courriel", "adresse_mail"),
    "telephone": ("telephone", "téléphone", "tel", "portable", "mobile", "phone"),
    "ville": ("ville", "commune", "city", "localite"),
    "montant": ("montant_ttc", "total_ttc", "ttc", "montant_ht", "total_ht", "ht",
                "montant", "total", "prix", "amount", "chiffre_affaires", "ca"),
    "date": ("date", "date_devis", "date_facture", "date_signature", "created_at",
             "date_creation", "annee"),
    "statut": ("statut", "status", "etat", "état"),
    "reference": ("reference", "référence", "ref", "numero", "numéro", "num", "id"),
}


def _plat(texte) -> str:
    """Minuscules, sans accents, sans ponctuation : la forme qui se compare."""
    s = unicodedata.normalize("NFD", str(texte or ""))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").lower()
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def _colonne(donnees: dict, famille: str):
    """La colonne de cette famille présente dans l'enregistrement, ou None."""
    index = {_plat(k): k for k in donnees}
    for synonyme in FAMILLES.get(famille, ()):
        clef = index.get(_plat(synonyme))
        if clef is None:
            continue
        valeur = str(donnees[clef] or "").strip()
        if not valeur:
            continue
        # UN NOM CONTIENT DES LETTRES. Relevé le 22/08 : un export portait une
        # colonne « Client » valant « 1 » (un drapeau) à côté de « Nom » ; la
        # fiche s'est intitulée « 1 ». Une valeur sans lettre n'est pas une
        # identité, on passe au synonyme suivant.
        if famille == "nom" and not re.search(r"[a-zA-Z\u00C0-\u024F]", valeur):
            continue
        return clef
    return None


def _valeur(donnees: dict, famille: str) -> str:
    clef = _colonne(donnees, famille)
    return str(donnees[clef]).strip() if clef else ""


def _jsonb(valeur) -> dict:
    """Un JSONB tel qu'asyncpg le rend : une CHAÎNE, pas un dict.

    Relevé en production le 22/08, traces Langfuse : `liste_clients` rendait
    « dictionary update sequence element #0 has length 1; 2 is required » — le
    message de `dict()` nourri d'une chaîne. Aucun codec JSON n'est posé sur le
    pool (`database/connection.py`), donc `row["data"]` arrive en texte. Le
    banc ne l'avait pas vu parce que sa fausse base rendait des dicts : une
    doublure qui ment sur le TYPE teste un code qui n'existe pas. Elle rend
    désormais des chaînes, comme la vraie.
    """
    if not valeur:
        return {}
    if isinstance(valeur, dict):
        return valeur
    if isinstance(valeur, (bytes, bytearray)):
        valeur = valeur.decode("utf-8", "replace")
    if isinstance(valeur, str):
        import json
        try:
            d = json.loads(valeur)
            return d if isinstance(d, dict) else {}
        except ValueError:
            return {}
    try:
        return dict(valeur)
    except (TypeError, ValueError):
        return {}


def _nom_complet(d: dict) -> str:
    """Nom ET prénom quand l'export les sépare : « DUPONT Marie », pas « DUPONT »."""
    nom = _valeur(d, "nom")
    prenom = _valeur(d, "prenom")
    if prenom and _plat(prenom) not in _plat(nom):
        return f"{nom} {prenom}".strip()
    return nom


def _fusion(ligne) -> dict:
    """Les en-têtes d'origine ET le vocabulaire normalisé, dans un seul dict.

    La migration 020 conserve les deux à dessein : `data` porte les en-têtes du
    fichier tel qu'il a été exporté (« Raison sociale », « Montant HT »),
    `champs` la même ligne ramenée au vocabulaire du type (« nom »,
    « montant_ht »). Reconnaître une colonne a donc DEUX chances au lieu d'une
    — et l'export dont personne n'a normalisé les en-têtes reste lisible.

    `data` est appliqué en dernier : à valeur égale, l'orthographe d'origine
    l'emporte pour l'affichage, parce que c'est celle que le client reconnaît.
    """
    champs = _jsonb(ligne["champs"]) if "champs" in ligne.keys() else {}
    return {**champs, **_jsonb(ligne["data"])}


_NOMBRE = re.compile(r"-?\d[\d\s  .,]*")


def _montant(texte) -> float:
    """« 12 450,50 € » → 12450.5. Rend 0.0 sur tout ce qui n'est pas un nombre.

    Les exports comptables français mélangent espaces insécables, virgules
    décimales et séparateurs de milliers. Un parseur naïf lit « 12 450,50 »
    comme 12, et le chiffre d'affaires d'un client devient faux sans que rien
    ne le signale — c'est le genre d'erreur qui ne se voit qu'en réunion.
    """
    m = _NOMBRE.search(str(texte or ""))
    if not m:
        return 0.0
    brut = m.group(0)
    for espace in (" ", " ", " "):
        brut = brut.replace(espace, "")
    # Le dernier séparateur rencontré est le décimal ; les autres sont des
    # milliers. « 1.234,56 » et « 1,234.56 » se lisent donc tous les deux.
    if "," in brut and "." in brut:
        decimal = "," if brut.rindex(",") > brut.rindex(".") else "."
        millier = "." if decimal == "," else ","
        brut = brut.replace(millier, "").replace(decimal, ".")
    elif "," in brut:
        brut = brut.replace(",", ".")
    try:
        return float(brut)
    except ValueError:
        return 0.0


def _euros(valeur: float) -> str:
    return f"{valeur:,.2f} €".replace(",", " ").replace(".", ",")


async def _jeux(conn, niveaux: list) -> list:
    lignes = await conn.fetch(
        "SELECT DISTINCT source_type FROM document_metadata "
        "WHERE access_level = ANY($1::text[]) ORDER BY source_type", niveaux)
    return [l["source_type"] for l in lignes]


def _jeu_clients(existants: list):
    """Le jeu de données qui contient les clients, quel que soit son nom.

    On ne suppose pas « client » : un import peut s'appeler « clients »,
    « CLIENTS 2025 », « base_clients ». On cherche donc la racine dans le nom.
    """
    for candidat in existants:
        if "client" in _plat(candidat) or "customer" in _plat(candidat):
            return candidat
    return None


# ═══════════════════════════════════════════════════════════════════════════
#  LISTE DES CLIENTS
# ═══════════════════════════════════════════════════════════════════════════
#
#  L'EXPORT DOIT SAVOIR RÉPONDRE À LA DEMANDE ENTIÈRE. Relevé le 23/08 :
#  « fais-moi un Excel avec une colonne pleine de tous les noms clients et une
#  colonne avec mon mail sur toutes les lignes ». Le skill ne savait produire
#  qu'un tableau figé (Client, Ville, Email, Téléphone) : le modèle a bien
#  fabriqué le fichier, a constaté qu'il ne portait pas la seconde colonne, et
#  s'est mis à DEMANDER l'adresse de son interlocuteur — deux tours de plus,
#  puis un troisième, sans jamais rien livrer. Une adresse que le serveur
#  connaît par la session, qui plus est.
#
#  Deux paramètres suffisent, et ils ne codent aucun métier :
#    · `colonnes` — celles qu'on garde (« juste les noms ») ;
#    · `ajouts`   — des colonnes CONSTANTES ({"E-mail": "@moi"}), où `@moi`
#      vaut l'adresse de la personne connectée. On ne la demande donc jamais.
_CLE_PAR_LIBELLE = {
    "client": "nom", "clients": "nom", "nom": "nom", "noms": "nom",
    "raison_sociale": "nom", "societe": "nom",
    "ville": "ville", "villes": "ville", "commune": "ville",
    "email": "email", "e_mail": "email", "mail": "email", "mails": "email",
    "adresse_mail": "email", "courriel": "email",
    "telephone": "telephone", "tel": "telephone", "portable": "telephone",
}
# « @moi », « mon mail »… : l'adresse de celui qui parle, connue du serveur.
_C_EST_MOI = ("moi", "@moi", "mon_email", "mon_mail", "mon_adresse",
              "mon_adresse_mail", "mon_courriel", "utilisateur", "moi_meme")


def _colonnes_gardees(data: dict) -> list | None:
    """Les colonnes demandées, ramenées aux clés connues. `None` = toutes.

    Le nom reste TOUJOURS : une liste de clients sans les clients n'existe pas.
    """
    brut = data.get("colonnes")
    if isinstance(brut, str):
        brut = re.split(r"[,;/]| et ", brut)
    if not isinstance(brut, (list, tuple)) or not brut:
        return None
    gardees = ["nom"]
    for x in brut:
        cle = _CLE_PAR_LIBELLE.get(_plat(x))
        if cle and cle not in gardees:
            gardees.append(cle)
    return gardees


def _colonnes_ajoutees(data: dict, user) -> list:
    """Les colonnes constantes demandées en plus : `{"E-mail": "@moi"}`.

    Bornées à trois : au-delà, ce n'est plus une liste de clients enrichie,
    c'est un autre fichier — et il se fabrique avec l'atelier de documents.
    """
    import json as _j
    brut = data.get("ajouts") if data.get("ajouts") is not None else data.get("colonnes_fixes")
    if isinstance(brut, str):
        try:
            brut = _j.loads(brut)
        except ValueError:
            brut = None
    if not isinstance(brut, dict):
        return []
    moi = str(getattr(user, "email", "") or "").strip()
    sorties = []
    for libelle, valeur in list(brut.items())[:3]:
        titre = str(libelle or "").strip()[:40]
        if not titre:
            continue
        texte = str("" if valeur is None else valeur).strip()
        if _plat(texte) in _C_EST_MOI:
            texte = moi
        sorties.append((titre, texte[:200]))
    return sorties


async def liste_clients(data: dict, user) -> dict:
    """Qui sont les clients, combien, et de quoi les joindre. UN appel."""
    from database.connection import get_db
    from security.acces import niveaux_visibles
    from skills.erreurs import SkillError

    niveaux = sorted(niveaux_visibles(getattr(user, "role", "")))
    try:
        async with get_db() as conn:
            existants = await _jeux(conn, niveaux)
            jeu = _jeu_clients(existants)
            if not jeu:
                # NE PAS RÉPONDRE « AUCUN CLIENT ». Un jeu de données absent et
                # un jeu vide se ressemblent dans une réponse, et l'assistant a
                # déjà conclu « les données ne sont pas importées » alors
                # qu'elles l'étaient sous un autre nom.
                return {
                    "trouve": False,
                    "jeux_de_donnees": existants,
                    "message": (
                        "Aucun jeu de données ne porte de nom de client. Ce n'est PAS "
                        "« il n'y a pas de clients » : c'est que rien n'a été importé "
                        "sous ce nom. Jeux disponibles : "
                        + (", ".join(existants) if existants else "aucun") + "."),
                    "a_faire": ("Dis-le tel quel à l'utilisateur, propose d'importer le "
                                "fichier des clients depuis Paramètres > Import de "
                                "données, et n'invente AUCUN nom."),
                }

            total = await conn.fetchval(
                "SELECT COUNT(*) FROM document_metadata "
                "WHERE source_type = $1 AND access_level = ANY($2::text[])",
                jeu, niveaux)
            lignes = await conn.fetch(
                "SELECT data, champs FROM document_metadata "
                "WHERE source_type = $1 AND access_level = ANY($2::text[]) "
                "ORDER BY ligne NULLS LAST LIMIT $3",
                jeu, niveaux, MAX_CLIENTS)
    except Exception as e:  # noqa: BLE001
        logger.warning("Liste des clients impossible : %s", e)
        raise SkillError("La base des clients est momentanément indisponible.")

    clients = []
    for l in lignes:
        d = _fusion(l)
        nom = _nom_complet(d)
        if not nom:
            continue
        clients.append({"nom": nom, "ville": _valeur(d, "ville"),
                        "email": _valeur(d, "email"), "telephone": _valeur(d, "telephone")})
    clients.sort(key=lambda c: _plat(c["nom"]))

    # LA LISTE COMPLÈTE, C'EST UN FICHIER. Relevé le 22/08 : « il dit qu'il
    # affiche tout, il n'affiche jamais de grosse quantité ». Un bloc d'écran
    # n'est pas fait pour 478 lignes, et le modèle ne les recopiera jamais.
    # Quand on veut tout, on produit un Excel — rangé par l'atelier, servi par
    # la route des documents, affiché en aperçu dans le chat comme n'importe
    # quel fichier produit.
    veut_fichier = str(data.get("fichier") or data.get("format") or "").strip().lower() in (
        "1", "true", "oui", "vrai", "xlsx", "excel", "fichier", "csv", "complet", "tout")
    gardees = _colonnes_gardees(data)
    ajouts = _colonnes_ajoutees(data, user)
    if veut_fichier and clients:
        return await _fichier_clients(clients, jeu, total, user, gardees, ajouts)

    # Pagination par initiale : « les clients en B », « la suite ».
    lettre = _plat(data.get("lettre") or "")[:1]
    if lettre:
        clients = [c for c in clients if _plat(c["nom"])[:1] == lettre]
    total_filtre = len(clients)
    tronque_ecran = total_filtre > MAX_AFFICHES
    clients = clients[:MAX_AFFICHES]

    if not clients:
        return {"trouve": False, "source_type": jeu, "nombre": 0,
                "message": (f"Le jeu « {jeu} » existe ({total} enregistrement(s)) mais "
                            "aucun nom de client n'a pu y être lu. Les colonnes ne "
                            "portent peut-être pas un nom reconnu."),
                "a_faire": "Propose d'appeler `interroger_donnees` pour voir les colonnes réelles."}

    colonnes = ["Client"] + [t for t, c in (("Ville", "ville"), ("Email", "email"),
                                            ("Téléphone", "telephone"))
                             if any(x[c] for x in clients)
                             and (gardees is None or c in gardees)]
    cles = {"Client": "nom", "Ville": "ville", "Email": "email", "Téléphone": "telephone"}
    bloc = {"type": "table",
            "columns": colonnes + [t for t, _ in ajouts],
            "rows": [[c[cles[t]] for t in colonnes] + [v for _, v in ajouts]
                     for c in clients]}

    n = len(clients)
    if lettre:
        compte = (f"{total_filtre} client{'s' if total_filtre > 1 else ''} dont le nom "
                  f"commence par « {lettre.upper()} » (sur {total} au total)"
                  + (f", les {n} premiers affichés." if tronque_ecran else ", tous affichés."))
    else:
        compte = (f"{total} client{'s' if total > 1 else ''} en base"
                  + (f", les {n} premiers affichés par ordre alphabétique." if tronque_ecran
                     else ", tous affichés."))
    return {
        "trouve": True,
        "source_type": jeu,
        "nombre": total,
        "affiches": n,
        "lettre": lettre.upper() or None,
        "clients": clients,
        "bloc_ui": bloc,
        "message_final": compte,
        "a_faire": ("Commence par cette phrase, mot pour mot : « " + compte + " ». "
                    "Puis AFFICHE la liste en insérant un bloc ```ui contenant EXACTEMENT "
                    "le contenu de `bloc_ui` — n'écris PAS les noms toi-même en texte, ne "
                    "dis pas un autre nombre que " + str(n) + " pour les affichés ni que "
                    + str(total) + " pour le total. "
                    + ("Pour la suite, rappelle `liste_clients` avec `lettre` (une initiale). "
                       if tronque_ecran else "")
                    + "Pour le détail d'UN client, c'est `fiche_client`."),
    }


async def _fichier_clients(clients: list, jeu: str, total: int, user,
                           gardees: list | None = None, ajouts: list | None = None) -> dict:
    """Toute la liste dans un .xlsx produit par l'atelier, avec son bloc `fichier`."""
    import asyncio
    from bureautique.atelier import ouvrir, ajouter, terminer
    proprio = str(getattr(user, "id", "") or "")
    ajouts = ajouts or []
    colonnes = [("Client", "nom"), ("Ville", "ville"), ("Email", "email"), ("Téléphone", "telephone")]
    colonnes = [(t_, c) for t_, c in colonnes
                if c == "nom" or (any(x.get(c) for x in clients)
                                  and (gardees is None or c in gardees))]
    entete = {"titre": "Liste des clients", "format": "xlsx"}
    elements = [{"type": "feuille", "nom": "Clients",
                 "entetes": [t_ for t_, _ in colonnes] + [t_ for t_, _ in ajouts],
                 "lignes": [[c.get(cle, "") for _, cle in colonnes] + [v for _, v in ajouts]
                            for c in clients]}]

    def _produire():
        jeton = ouvrir(entete, proprio)
        ajouter(jeton, elements, proprio)
        return jeton, terminer(jeton, proprio)

    try:
        jeton, fiche = await asyncio.to_thread(_produire)
    except Exception as e:  # noqa: BLE001
        logger.warning("Excel des clients impossible : %s", e)
        from skills.erreurs import SkillError
        raise SkillError("Le fichier des clients n'a pas pu être produit. Réessayez, ou "
                         "demandez la liste à l'écran (par initiale).")

    # `titre` en plus du nom de fichier : c'est par lui que la réhydratation
    # reconnaît, au tour suivant, une vignette inventée qui parle de CE
    # fichier-là — et la remplace par le bloc réel (cf. `_designe_le_meme`).
    bloc = {"type": "fichier", "url": f"/api/documents/{jeton}", "nom": "clients.xlsx",
            "titre": entete["titre"], "format": "xlsx", "octets": fiche.get("octets")}
    entetes = [t_ for t_, _ in colonnes] + [t_ for t_, _ in ajouts]
    compte = (f"{total} client{'s' if total > 1 else ''}, la liste complète est dans le fichier "
              f"Excel ci-dessous ({len(clients)} lignes, colonnes : "
              + ", ".join(entetes) + ").")
    return {
        "trouve": True, "source_type": jeu, "nombre": total, "affiches": len(clients),
        "fichier": bloc["url"], "bloc_ui": bloc, "message_final": compte,
        "a_faire": ("Dis : « " + compte + " », puis insère un bloc ```ui contenant EXACTEMENT "
                    "le contenu de `bloc_ui` (type `fichier`) : l'écran affiche l'aperçu du "
                    "tableau et le bouton de téléchargement. N'écris AUCUN nom toi-même. Le "
                    "lien vaut 24 h."),
    }


# ═══════════════════════════════════════════════════════════════════════════
#  FICHE D'UN CLIENT
# ═══════════════════════════════════════════════════════════════════════════
async def fiche_client(data: dict, user) -> dict:
    """TOUT ce qu'on sait d'un client, à travers TOUS les jeux importés.

    Le point clé : on ne se limite pas au fichier des clients. Un client
    n'existe pas dans une table, il existe dans les devis, les factures, les
    chantiers — et c'est le recoupement qui répond à « combien il nous a
    rapporté ». Chercher dans un seul jeu rendrait une fiche vide et juste.
    """
    from database.connection import get_db
    from security.acces import niveaux_visibles
    from skills.erreurs import SkillError

    demande = (data.get("nom") or data.get("client") or data.get("demande") or "").strip()
    if not demande:
        raise SkillError("Quel client ? Donne son nom dans `nom`.")

    niveaux = sorted(niveaux_visibles(getattr(user, "role", "")))
    cible = _plat(demande)

    try:
        async with get_db() as conn:
            existants = await _jeux(conn, niveaux)
            # Une seule lecture pour TOUS les jeux : la fiche croise les
            # sources, la faire en N requêtes multiplierait les allers-retours
            # pour un volume que Postgres filtre sans effort.
            lignes = await conn.fetch(
                "SELECT source_type, data, champs FROM document_metadata "
                "WHERE access_level = ANY($1::text[]) "
                "  AND (data::text ILIKE $2 OR champs::text ILIKE $2) "
                "LIMIT 2000",
                niveaux, f"%{demande}%")
    except Exception as e:  # noqa: BLE001
        logger.warning("Fiche client impossible : %s", e)
        raise SkillError("Les données clients sont momentanément indisponibles.")

    par_jeu: dict = {}
    identite: dict = {}
    for l in lignes:
        d = _fusion(l)
        # LE ILIKE RATISSE TROP LARGE, ET C'EST UN PIÈGE À CHIFFRES.
        # Relevé au banc : un chantier de la mairie portait « accès par la
        # parcelle de SCI Les Tilleuls » en commentaire, et se retrouvait
        # compté dans la fiche des Tilleuls. Un enregistrement n'appartient à
        # un client que si c'est SA COLONNE D'IDENTITÉ qui porte le nom —
        # « Client », « Raison sociale », « Société ». Le reste est du contexte.
        #
        # Quand aucune colonne d'identité n'existe (un fichier sans en-tête
        # reconnu), on retombe sur la correspondance large : mieux vaut une
        # ligne de trop, visible et vérifiable, qu'une fiche vide.
        colonne_identite = _colonne(d, "nom")
        if colonne_identite is not None:
            if cible not in _plat(d[colonne_identite]):
                continue
        elif not any(cible in _plat(v) for v in d.values()):
            continue
        par_jeu.setdefault(l["source_type"], []).append(d)
        if not identite and "client" in _plat(l["source_type"]):
            identite = d

    if not par_jeu:
        return {
            "trouve": False, "nom_demande": demande, "jeux_de_donnees": existants,
            "message": (f"Aucun enregistrement ne mentionne « {demande} » dans les "
                        f"{len(existants)} jeu(x) de données importés."),
            "a_faire": ("Dis-le sans détour et n'invente RIEN. Propose d'appeler "
                        "`liste_clients` pour vérifier l'orthographe exacte du nom."),
        }

    # ── Le recoupement : combien, pour combien, dans quel jeu ──────────────
    resume, total_general = [], 0.0
    detail_devis = []
    # Les jeux réellement additionnés : un chiffre qui circule sans sa source
    # finit par être cité en réunion sans que personne ne sache d'où il sort.
    sources_ca = []
    for jeu, enregistrements in sorted(par_jeu.items(), key=lambda x: -len(x[1])):
        somme = 0.0
        for d in enregistrements:
            colonne = _colonne(d, "montant")
            if colonne:
                somme += _montant(d[colonne])
        resume.append({"jeu": jeu, "enregistrements": len(enregistrements),
                       "montant_total": _euros(somme) if somme else ""})
        # Le chiffre d'affaires ne compte QUE les jeux de facturation : additionner
        # les devis ET les factures compterait deux fois la même affaire.
        if somme and any(mot in _plat(jeu) for mot in ("factur", "vente", "ca", "chiffre")):
            total_general += somme
            sources_ca.append(jeu)
        if any(mot in _plat(jeu) for mot in ("devis", "quote", "offre", "factur")):
            for d in enregistrements[:MAX_LIGNES_PAR_JEU]:
                detail_devis.append({
                    "jeu": jeu,
                    "reference": _valeur(d, "reference"),
                    "date": _valeur(d, "date"),
                    "statut": _valeur(d, "statut"),
                    "montant": _valeur(d, "montant"),
                })

    # Sans jeu de facturation identifié, le total le plus élevé fait foi —
    # et on DIT d'où il vient, pour qu'un chiffre ne circule jamais sans source.
    origine_ca = ", ".join(sources_ca)
    if not total_general and resume:
        meilleur = max(resume, key=lambda r: _montant(r["montant_total"]))
        total_general = _montant(meilleur["montant_total"])
        origine_ca = meilleur["jeu"]

    fiche = {"Client": _nom_complet(identite) or demande}
    for etiquette, famille in (("Ville", "ville"), ("Email", "email"), ("Téléphone", "telephone")):
        v = _valeur(identite, famille)
        if v:
            fiche[etiquette] = v
    for r in resume:
        fiche[r["jeu"].capitalize()] = (f"{r['enregistrements']}"
                                        + (f" · {r['montant_total']}" if r["montant_total"] else ""))
    if total_general:
        fiche["Chiffre d'affaires"] = f"{_euros(total_general)} (source : {origine_ca})"

    return {
        "trouve": True,
        "client": fiche["Client"],
        "identite": identite,
        "par_jeu": resume,
        "devis": detail_devis,
        "chiffre_affaires": _euros(total_general) if total_general else None,
        "source_chiffre_affaires": origine_ca if total_general else None,
        "bloc_ui": {"type": "keyvalue",
                    "rows": [[k, v] for k, v in fiche.items()]},
        "message_final": (f"Voici ce que je sais de {fiche['Client']} : "
                          + ", ".join(f"{r['enregistrements']} {r['jeu']}" for r in resume)
                          + (f", pour un chiffre d'affaires de {_euros(total_general)}."
                             if total_general else ".")),
        "a_faire": ("AFFICHE la fiche : insère un bloc ```ui contenant EXACTEMENT le "
                    "contenu de `bloc_ui`. Si `devis` n'est pas vide, ajoute un second "
                    "bloc ```ui de type `table` (champs `columns` et `rows`) avec les "
                    "colonnes Référence, Date, Statut, Montant. Cite les chiffres TELS QUELS — ne les recalcule "
                    "pas, ne les arrondis pas, et rappelle la source du chiffre "
                    "d'affaires."),
    }


# ═══════════════════════════════════════════════════════════════════════════
#  POINT SUR LES MAILS
# ═══════════════════════════════════════════════════════════════════════════
async def check_mails(data: dict, user) -> dict:
    """Le point sur le courrier récent, prêt à être résumé en UN message.

    Ce skill ne résume pas lui-même : il RASSEMBLE. Faire écrire un résumé par
    message coûterait un appel LLM chacun — soit, sur vingt messages, vingt
    passages dans la cascade. Il rend donc la matière d'un seul coup, avec la
    consigne de tout traiter dans la même réponse.
    """
    from mail.skills import lire_mails
    from skills.erreurs import SkillError

    # Une période demandée ⇒ le détail va au maximum (voir lire_mails).
    _periode = data.get("depuis") or data.get("periode") or data.get("jours")
    try:
        limite = int(data.get("limite") or (25 if _periode else 15))
    except (TypeError, ValueError):
        limite = 25 if _periode else 15
    limite = max(1, min(limite, 25))

    # La période vient de l'utilisateur (« cette semaine » → jours=7). Sans
    # elle, les plus récents. Avec elle, le TOTAL de la période est exact même
    # si le détail reste borné — c'est la différence entre « 25 mails » et
    # « 84 mails cette semaine, voici les 25 derniers ».
    depuis = data.get("depuis") or data.get("periode") or data.get("jours")
    brut = await lire_mails({"mailbox": data.get("mailbox"),
                             "dossier": data.get("dossier") or "recus",
                             "limite": limite, "depuis": depuis}, user)

    messages = brut.get("messages") or brut.get("mails") or []
    if not isinstance(messages, list):
        raise SkillError("La messagerie a répondu dans un format inattendu.")

    if not messages:
        return {"nombre": 0, "boite": brut.get("boite") or brut.get("mailbox"),
                "message_final": "Aucun message récent dans cette boîte.",
                "a_faire": "Dis-le simplement, sans meubler."}

    def _champ(m, *noms):
        for n in noms:
            v = m.get(n)
            if v:
                return str(v)
        return ""

    releve = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        objet = _champ(m, "objet", "subject", "sujet")
        releve.append({
            "de": _champ(m, "de", "from", "expediteur", "sender"),
            "objet": objet,
            "date": _champ(m, "date", "recu_le", "receivedAt", "received_at"),
            "extrait": _champ(m, "apercu", "extrait", "preview", "body", "corps")[:400],
            # « Re: » n'est pas un détail : une réponse dans un fil en cours est
            # ce qu'on veut voir en premier quand on fait le point.
            "reponse_dans_un_fil": bool(re.match(r"\s*(re|rép|rep)\s*:", objet, re.I)),
            # LA MESSAGERIE REND `lu`, PAS `non_lu` — et l'écart était invisible.
            # Le skill cherchait une clé qui n'existe nulle part dans
            # `mail/lecture.py` : le compteur de non-lus serait resté à zéro
            # pour toujours, sans erreur, sans trace. Relevé au banc.
            # `.get("lu", True)` : un message dont l'état est inconnu n'est PAS
            # annoncé comme non lu — on ne réveille pas sur une supposition.
            "non_lu": not bool(m.get("lu", True)),
            # Une pub n'appelle pas de réponse. Le dire ici évite au modèle de
            # proposer poliment de répondre à un catalogue d'automne.
            "automatique": bool(m.get("expediteur_automatique")),
            "interne": bool(m.get("expediteur_interne")),
        })

    fils = sum(1 for r in releve if r["reponse_dans_un_fil"])
    non_lus = sum(1 for r in releve if r["non_lu"])
    total = brut.get("total_periode")
    tronque = bool(brut.get("tronque"))
    compte = brut.get("compte") or f"{len(releve)} message(s)."

    return {
        "nombre": len(releve),
        "total_periode": total,
        "tronque": tronque,
        "compte": compte,
        "reponses_dans_un_fil": fils,
        "non_lus": non_lus,
        "boite": brut.get("boite") or brut.get("mailbox"),
        "messages": releve,
        "message_final": (compte
                          + (f" Parmi les détaillés : {fils} réponse(s) à un fil en cours" if fils else "")
                          + (f", {non_lus} non lu(s)" if non_lus and fils else
                             f" Parmi les détaillés : {non_lus} non lu(s)" if non_lus else "")
                          + ("." if (fils or non_lus) else "")),
        "a_faire": (
            "Commence par le COMPTE, mot pour mot : « " + compte + " » — c'est le "
            "total qui répond à « combien », pas le nombre de messages détaillés. "
            + ("Le détail ne couvre PAS toute la période : dis-le, et propose de "
               "cibler (un expéditeur, un sujet, une journée) si l'utilisateur veut le reste. "
               if tronque else "")
            + "Fais le point en UN SEUL message, sans rappeler ce skill. Pour chaque "
            "message : l'expéditeur, l'objet, et UNE phrase de résumé tirée de "
            "l'extrait — jamais de ta mémoire. Mets EN PREMIER ceux marqués "
            "`reponse_dans_un_fil` : ce sont des échanges en cours. "
            "N'en propose AUCUNE pour les messages marqués `automatique` : ce sont "
            "des envois de masse, y répondre n'a pas de sens. "
            "Quand un message appelle visiblement une réponse (question posée, "
            "demande de devis, relance), propose une réponse courte en deux ou trois "
            "lignes, présentée comme une PROPOSITION à valider — n'envoie rien : "
            "l'envoi passe par `redaction_email`, que l'utilisateur devra approuver. "
            "Si un extrait est vide, dis que le contenu n'a pas pu être lu au lieu "
            "d'inventer un résumé."),
    }


# ── Déclarations : tout ce que le système doit savoir, ICI ──────────────────
from skills.registre import Declaration

SKILLS = {
    "liste_clients": Declaration(
        fonction=liste_clients,
        description=(
            "LISTE les clients de l'entreprise en UN SEUL appel : le nombre exact, "
            "les noms, et le contact quand il est connu. C'est le skill a appeler "
            "pour « la liste des clients », « combien de clients », « qui sont nos "
            "clients » — PAS `interroger_donnees`, qui demanderait trois "
            "allers-retours pour la meme reponse, ni `rechercher_documents`, qui "
            "approxime. Le resultat donne un bloc ```ui a inserer TEL QUEL (60 noms "
            "au plus par appel, par ordre alphabetique ; `lettre` = une initiale pour "
            "la suite). Pour la liste COMPLETE, ou des qu'on demande « tous », « tout », "
            "« la liste entiere », un export, un Excel : passe `fichier: true` — le "
            "resultat est un fichier Excel avec apercu dans le chat, jamais une liste "
            "a recopier. Ne cherche JAMAIS sur le web pour cette question : les "
            "clients sont une donnee interne. "
            "LE FICHIER SE FACONNE ICI, en un seul appel : `colonnes` garde celles "
            "qu'on demande (`[\"Client\"]` pour « juste les noms ») et `ajouts` ajoute "
            "des colonnes CONSTANTES, repetees sur toutes les lignes "
            "(`{\"E-mail\": \"@moi\"}`). `@moi` vaut l'adresse de la personne connectee : "
            "elle est connue du serveur, ne la demande JAMAIS a l'utilisateur. "
            "N'enchaine pas d'autre action apres : le fichier est produit, montre-le"),
        requis=[], optionnels=["lettre", "fichier", "colonnes", "ajouts"],
        effet="lecture",
        libelle="je liste les clients"),
    "fiche_client": Declaration(
        fonction=fiche_client,
        description=(
            "TOUT ce que l'entreprise sait d'UN client, en UN SEUL appel et a "
            "travers TOUS les fichiers importes : devis (nombre, references, "
            "montants, statuts), factures, chantiers, chiffre d'affaires genere, "
            "coordonnees. C'est le skill a appeler des qu'une question porte sur un "
            "client nomme — « parle-moi de X », « combien de devis pour X », « quel "
            "chiffre d'affaires avec X ». `nom` : le nom du client. Les chiffres "
            "rendus sont EXACTS : cite-les tels quels, ne les recalcule pas"),
        requis=["nom"], optionnels=[],
        effet="lecture",
        libelle="je rassemble la fiche du client"),
    "check_mails": Declaration(
        fonction=check_mails,
        description=(
            "FAIT LE POINT sur le courrier recent en UN SEUL appel : les derniers "
            "messages, lesquels sont des reponses a un fil en cours, lesquels sont "
            "non lus. A appeler pour « fais un check de mes mails », « quoi de neuf "
            "dans ma boite », « resume-moi mes mails ». Rends ensuite UN SEUL "
            "message : un resume par mail, et une PROPOSITION de reponse quand le "
            "message en appelle une. N'envoie rien — l'envoi passe par "
            "`redaction_email` et sa validation. `depuis` : OBLIGATOIRE des qu'une "
            "periode est nommee (« cette semaine » → \"7j\", « ce mois » → \"30j\", ou "
            "une date AAAA-MM-JJ) : le resultat donne alors le TOTAL EXACT de la "
            "periode en plus du detail des 25 plus recents. `limite` : 1 a 25 (defaut 15)"),
        requis=[], optionnels=["mailbox", "dossier", "limite", "depuis"],
        effet="lecture",
        libelle="je fais le point sur les mails"),
}

"""
Agent 2 — Appels d'offres / Chiffrage / Analyse de plans (BTP — Duret & Sols)
Rôle : analyse de plans et documents techniques (CCTP, DPGF, plans), extraction
structurée (revêtements, surfaces, plinthes, contraintes), recherche de dossiers
similaires, préparation d'une base de pré-chiffrage — TOUJOURS validée par Benoît.

Pipeline : preprocess → vision → extraction → [browser?] → similar_projects → prechiffrage

Sécurité / RGPD :
- Les fichiers sont ré-encodés via Pillow → suppression des métadonnées EXIF/GPS.
- Le pré-chiffrage n'est JAMAIS validé par l'IA : il est rendu comme une estimation
  indicative, marquée comme telle, à valider par un humain avant tout usage. Aucune
  porte d'accord devant la LECTURE (voir prechiffrage_node).
"""
import asyncio
import base64
import io
import json
import logging
import re

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langgraph.graph import StateGraph, END
from agents.state import AgentState
from llm.router import get_llm, LLMTier

logger = logging.getLogger("duret.agent2")

VISION_PROMPT = (
    # LE PRÉPROMPT DU CHIFFRAGE (01/09, demande de Noa) : l'analyse ne se
    # contente plus de décrire — elle INVENTORIE tout, DÉDUIT une échelle des
    # cotes lisibles, et livre des estimations en fourchettes dont chaque
    # hypothèse est DITE. Trois régimes de mesure, jamais confondus : LU
    # (coté sur le plan), ESTIMÉ (déduit, avec sa base), NON MESURABLE.
    "Tu es l'assistant études & chiffrage de Duret & Sols (travaux de sols et revêtements, BTP). "
    "Analyse ce plan (2D ou 3D), ce document technique ou cette photo pour préparer un MÉTRÉ et "
    "un CHIFFRAGE. Travaille en CINQ temps, dans cet ordre :\n"
    # LA LÉGENDE AVANT TOUT (02/09). Leçon d'un workflow de métré multi-passes
    # en production : les conventions graphiques CHANGENT d'un bureau d'études
    # à l'autre. Les supposer fausse tout ce qui suit, et l'erreur ne se voit
    # pas — elle ressemble à une lecture. On lit la légende, puis on s'y tient.
    "1. CARTOUCHE ET LÉGENDE : lis d'abord le cartouche (titre, niveau, échelle, "
    "date, indice, lot) et la légende, trame par trame et symbole par symbole. "
    "La légende du plan PRIME sur toute convention que tu croirais connaître : "
    "elle varie d'un bureau d'études à l'autre. Si elle est absente, dis-le.\n"
    "2. INVENTAIRE EXHAUSTIF : chaque zone et chaque élément, un par un. Locaux et "
    "pièces (nature, usage), pans de murs et cloisons, ouvertures, revêtements de "
    "sol indiqués (carrelage, résine, béton, sol souple, parquet…), plinthes, "
    "seuils, joints de dilatation, escaliers, niveaux, réservations, existant à "
    "déposer, chapes. Rien d'anecdotique : tout ce qui se voit se liste, c'est la "
    "matière du DPGF. BALAIE LE PLAN ZONE PAR ZONE (nord-ouest, nord-est, centre, "
    "sud-ouest, sud-est) plutôt qu'au fil de l'œil : c'est ce qui évite d'oublier "
    "les petits locaux, sas, gaines techniques et circulations.\n"
    "3. ÉCHELLE : cherche d'abord les COTES LISIBLES et l'échelle du cartouche. "
    "S'il en existe UNE seule, sers-t'en pour DÉDUIRE les autres dimensions par "
    "proportion (un mur coté 8 m qui en vaut deux fois un autre donne 4 m pour le "
    "second). Sans aucune cote, appuie-toi sur des références de taille connues et "
    "dis laquelle : porte 0,90 m, baie vitrée 2,20 à 2,40 m, hauteur d'étage "
    "2,70 m, place de voiture 2,50 × 5 m, carreau standard 60 × 60 cm.\n"
    # MESURER SUR UNE PHOTO N'EST PAS MESURER SUR UN PLAN (02/09, demande de
    # Noa). Un plan est à l'échelle partout ; une photo ne l'est nulle part.
    # Sans ces règles, le modèle rend des mètres carrés avec l'aplomb qu'il
    # aurait sur un plan coté, et un chiffrage part sur des quantités fausses
    # que rien ne signale. Les deux apports qui changent tout : COMPTER un
    # motif répété au lieu d'estimer une longueur, et DIRE les trois limites
    # qui rendent une mesure photographique fragile.
    "SUR UNE PHOTO, l'échelle se construit autrement. Cherche dans la scène un "
    "objet de dimension connue et NOMME-le : porte (0,83 ou 0,93 m de passage, "
    "2,04 m de haut), marche (giron 25 à 30 cm, hauteur 17 à 18 cm), carreau, "
    "plinthe (7 à 10 cm), prise (8,5 cm), interrupteur (1,10 m du sol), "
    "parpaing (20 × 20 × 50), palette (80 × 120), porte de garage (2,40 m), "
    "personne (1,70 m). COMPTE PLUTÔT QUE D'ESTIMER dès qu'un motif se répète : "
    "quinze carreaux de 60 cm font 9 m, et c'est bien plus sûr qu'une longueur "
    "jugée à l'œil ; vaut pour les carreaux, les lames, les marches, les "
    "parpaings, les poteaux, les dalles de plafond. Trois limites à DIRE, "
    "jamais à taire : une longueur qui FUIT vers le fond est sous-estimée et ne "
    "vaut qu'en ordre de grandeur ; l'étalon ne vaut que pour ce qui se trouve "
    "à la MÊME distance que lui ; une photo prise en biais, ou au grand angle, "
    "déforme les bords. Sur photo, élargis la fourchette et dis pourquoi.\n"
    "4. QUANTITATIFS ESTIMÉS : pour chaque poste chiffrable, donne surface (m²), "
    "linéaire (ml) ou nombre, en FOURCHETTE (« séjour : 32 à 36 m² »), avec la "
    "base de l'estimation. Trois régimes, jamais confondus : une mesure LUE se "
    "cite telle quelle ; une mesure ESTIMÉE s'annonce comme telle avec son "
    "hypothèse (« estimé d'après la porte prise à 0,90 m ») ; ce qui n'est ni "
    "lisible ni estimable est dit NON MESURABLE, sans invention.\n"
    "5. SYNTHÈSE POUR LE CHIFFRAGE : contraintes techniques (accès, phasage, "
    "supports, existant à déposer, chape à prévoir), points à vérifier sur site, "
    "et correspondances avec le CCTP quand il est fourni. Si PLUSIEURS images ou "
    "pages sont fournies (plan + coupe + photo), CROISE-les : dis ce que chacune "
    "apporte et signale toute contradiction entre elles. "
    # RECALER LA PHOTO SUR LE PLAN (02/09). « Croise-les » ne suffisait pas :
    # le modèle décrivait les deux documents l'un après l'autre sans jamais
    # dire QUELLE PARTIE du plan la photo montrait, ni lequel des deux croire.
    # La règle de partage vient du métier : un plan dit les dimensions, une
    # photo dit l'état. Confondre les deux fait chiffrer un local sur un plan
    # périmé, ou mesurer une surface à l'œil quand la cote existe.
    "PHOTO ET PLAN ENSEMBLE : dis D'ABORD d'où la photo est prise et quelle "
    "zone du plan elle montre, en t'appuyant sur des repères communs "
    "(ouvertures, poteaux, angles, changements de revêtement). Puis répartis "
    "les rôles : pour les DIMENSIONS, le plan fait foi ; pour l'ÉTAT réel "
    "(dégradations, existant à déposer, réseaux apparents, obstacles, accès), "
    "c'est la photo. Ce que l'une montre et que l'autre ignore est justement ce "
    "qui coûte : signale-le. Et toute CONTRADICTION (cloison ajoutée, "
    "revêtement différent de celui prévu) se dit en clair : c'est souvent "
    "l'information la plus chère du dossier. "
    # UN MÉTRÉ QUI NE DIT PAS SES TROUS SE FAIT PRENDRE POUR UN MÉTRÉ FINI.
    # Deuxième leçon du workflow multi-passes : sa dernière étape ne fusionne
    # pas seulement, elle JUGE son propre résultat. Sans ce verdict, une
    # analyse partielle a exactement l'allure d'une analyse complète.
    "TERMINE par un verdict en deux lignes : ce qui MANQUE pour chiffrer "
    "vraiment (cotes absentes, revêtements non spécifiés, zones illisibles), et "
    "si ce relevé est exploitable tel quel ou s'il demande une reprise humaine. "
    "Ne commence pas par une salutation : entre directement dans l'analyse, "
    "sauf si la demande te salue elle-même. "
    "Typographie : n'utilise JAMAIS de tiret cadratin ni de tiret demi-cadratin ; emploie plutôt une virgule, un deux-points, une parenthèse ou un point. "
    # LA REGLE CI-DESSUS A EU UN EFFET DE BORD, VISIBLE A L'ECRAN.
    # Privé de tiret, le modèle a pris le deux-points pour puce, et chaque
    # ligne de liste sortait ainsi : « : Maison : 120 m2. » — deux fois le
    # même signe, une fois comme puce, une fois comme séparateur. Relevé en
    # recette le 27/08 sur toutes les analyses de plan. L'interdit ne visait
    # que les tirets LONGS ; le tiret simple reste la bonne puce.
    "Pour une liste, commence chaque ligne par un tiret simple suivi d'une "
    "espace, jamais par un deux-points."
)

# Taille max d'image envoyée au modèle vision (coût / limites API).
_MAX_IMG_WIDTH = 1568

# COMBIEN DE PAGES D'UN PDF PARTENT À LA VISION.
#
# Une seule, jusqu'ici : `load_page(0)`. Or un dossier de plans, c'est un plan
# de masse, des coupes, des façades, parfois un descriptif — et l'assistant
# n'en voyait que la première feuille tout en répondant comme s'il avait tout
# lu. Rien ne signalait le reste : ni l'utilisateur ni le modèle ne pouvaient
# le savoir.
#
# Cinq est un compromis assumé : chaque page est une image de plus dans la
# requête, donc un coût et une latence de plus, et les modèles de vision se
# dégradent quand on les noie. Au-delà, on prend les cinq premières et ON LE
# DIT — une troncature annoncée est une information ; silencieuse, c'est une
# erreur.
MAX_PAGES_PDF = 5


# ── Nœuds ────────────────────────────────────────────────────────────

# ── Les fichiers d'un message ────────────────────────────────────────

# Combien de fichiers un même message peut porter. Dix, parce que c'est le
# geste réel (les photos d'une visite, les pièces d'un dossier) et parce que
# chacun coûte un appel de vision : au-delà, un tour dépasserait son temps
# imparti sans que personne l'ait demandé. Le plafond est appliqué au plus tôt,
# côté routeur, et il est DIT.
MAX_PIECES = 10


def pieces_du_tour(state: AgentState) -> list:
    """Les fichiers de CE tour, toujours sous forme de liste.

    Un envoi d'un seul fichier n'a pas de forme à part : c'est une liste d'un
    élément. Les champs `attachment_*` au singulier (file d'attente, tâches
    planifiées, clients plus anciens) se replient ici sur la même liste — un
    seul chemin ensuite, donc un seul comportement à vérifier.
    """
    pieces = state.get("attachments")
    if pieces:
        return list(pieces)[:MAX_PIECES]
    if state.get("attachment_b64"):
        return [{"nom": state.get("attachment_name") or "document",
                 "mime": state.get("attachment_mime") or "",
                 "b64": state.get("attachment_b64")}]
    return []


def _nettoyer_image(donnees: bytes) -> bytes:
    """Ré-encode une image : plus d'EXIF/GPS, et une largeur bornée."""
    from PIL import Image
    img = Image.open(io.BytesIO(donnees)).convert("RGB")
    if img.width > _MAX_IMG_WIDTH:
        ratio = _MAX_IMG_WIDTH / img.width
        img = img.resize((_MAX_IMG_WIDTH, int(img.height * ratio)))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=80)  # nouvel encodage = sans métadonnées EXIF
    return out.getvalue()


def _preparer_piece(piece: dict) -> dict:
    """Un fichier joint -> ses pages nettoyées et sa référence de dépôt.

    Fonction PURE au sens qui compte ici : elle ne touche ni à l'état ni au
    réseau, elle ne lève pas, et elle rend toujours une fiche — avec `pages`
    si le fichier est exploitable, avec `erreur` sinon. C'est ce qui permet de
    la lancer dans un thread, pour cinq fichiers à la fois.
    """
    import base64 as _b64
    nom = piece.get("nom") or "document"
    mime = (piece.get("mime") or "").lower()
    try:
        raw = _b64.b64decode(piece.get("b64") or "")
    except Exception:
        return {"nom": nom, "erreur": "base64 invalide"}
    if not raw:
        return {"nom": nom, "erreur": "fichier vide"}

    # PDF -> rendre ses pages en images (PyMuPDF, import optionnel).
    pages_brutes, pages_totales = [], 0
    if "pdf" in mime or nom.lower().endswith(".pdf"):
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(stream=raw, filetype="pdf")
            pages_totales = doc.page_count
            for numero in range(min(pages_totales, MAX_PAGES_PDF)):
                pix = doc.load_page(numero).get_pixmap(dpi=150)
                pages_brutes.append(pix.tobytes("png"))
            if not pages_brutes:
                return {"nom": nom, "erreur": "PDF sans page"}
            raw = pages_brutes[0]
        except ImportError:
            return {"nom": nom, "erreur": "PDF non supporté (PyMuPDF absent)"}
        except Exception as e:  # noqa: BLE001
            return {"nom": nom, "erreur": f"PDF illisible ({type(e).__name__})"}

    try:
        octets = _nettoyer_image(raw)
    except Exception as e:  # noqa: BLE001
        return {"nom": nom, "erreur": f"image illisible ({type(e).__name__})"}

    # Les pages SUIVANTES du PDF, nettoyées comme la première. Une page
    # illisible n'interrompt pas l'analyse des autres : mieux vaut quatre pages
    # sur cinq qu'un échec entier.
    pages = [octets]
    for suivante in pages_brutes[1:]:
        try:
            pages.append(_nettoyer_image(suivante))
        except Exception as e:  # noqa: BLE001
            logger.info("Page de PDF illisible, ignorée : %s", e)

    # LA PHOTO EST RANGÉE AU DÉPÔT, et c'est ce qui rend la retouche possible.
    # Sans cela l'image ne vit que le temps du tour, en base64 dans l'état : au
    # tour suivant, « change la terrasse sur cette photo » n'aurait plus de
    # source, et le modèle repartirait d'une génération neuve — donc d'une
    # AUTRE maison. L'import est optionnel : là où l'offre visuelle n'existe
    # pas, il ne se passe simplement rien.
    cle_visuel = None
    try:
        from visuels.depot import deposer_octets
        cle_visuel = deposer_octets(octets, "image/jpeg")
    except ImportError:
        pass
    except Exception as e:  # noqa: BLE001 — un dépôt raté ne casse pas l'analyse
        logger.info("Dépôt de la photo jointe impossible : %s", e)

    return {
        "nom": nom,
        "mime": "image/jpeg",
        "pages": [_b64.b64encode(p).decode() for p in pages],
        "cle": cle_visuel,
        "pages_totales": pages_totales or None,
        "pages_ignorees": (max(0, pages_totales - len(pages)) if pages_totales else 0) or None,
    }


async def preprocess_attachment_node(state: AgentState) -> dict:
    """Prétraite CHAQUE fichier joint : PDF -> images (jusqu'à MAX_PAGES_PDF
    pages), suppression EXIF/GPS des photos (Pillow), dépôt au magasin d'images.

    UN MESSAGE PORTE PLUSIEURS FICHIERS (07/09). Ce nœud ne lisait que
    `attachment_b64`, au singulier : joindre cinq photos obligeait à envoyer
    cinq messages, et l'assistant n'avait alors jamais le lot sous les yeux —
    relevé en production le 07/09, « fais le photomontage sur toutes les
    photos » n'a porté que sur une seule. Chaque fichier garde ici son identité
    (son nom, ses pages, sa référence de dépôt) : la vision les analyse ensuite
    un par un, et les nomme.

    UN FICHIER ILLISIBLE N'ARRÊTE PAS LES AUTRES : il ressort avec sa raison,
    et cette raison est dite dans la réponse. Quatre analyses sur cinq valent
    mieux qu'un échec entier — et un fichier tombé en silence est pire que les
    deux.

    Le travail est CPU-bound (Pillow, PyMuPDF) : chaque fichier part dans un
    thread. Sur cinq photos, la boucle événementielle restait bloquée le temps
    de les décoder toutes.
    """
    pieces = pieces_du_tour(state)
    if not pieces:
        return {}

    preparees = await asyncio.gather(*[asyncio.to_thread(_preparer_piece, p) for p in pieces])
    retenues = [p for p in preparees if p.get("pages")]
    ecartees = [p for p in preparees if not p.get("pages")]

    if not retenues:
        detail = " ; ".join(f"{p['nom']} ({p.get('erreur', 'illisible')})" for p in ecartees)
        return {"error": "pieces_illisibles",
                "llm_response": f"Aucun des fichiers joints n'a pu être lu : {detail}."}

    premiere = retenues[0]
    return {
        # La liste porte les fichiers RETENUS puis les écartés : la vision lit
        # les premiers et signale les seconds. Une seule liste, pas deux champs
        # à tenir synchronisés.
        "attachments": retenues + ecartees,
        # LES CHAMPS AU SINGULIER DÉSIGNENT LE PREMIER FICHIER. Tout ce qui ne
        # sait pas encore compter (extraction, pré-chiffrage d'un seul plan,
        # file d'attente, tâches planifiées) continue de fonctionner tel quel.
        "attachment_b64": premiere["pages"][0],
        "attachment_mime": "image/jpeg",
        "attachment_name": premiere["nom"],
        "attachment_visuel_cle": premiere.get("cle"),
        "attachment_visuel_cles": [p["cle"] for p in retenues if p.get("cle")],
        "attachment_pages": premiere["pages"],
        "pages_totales": premiere.get("pages_totales"),
        "pages_ignorees": premiere.get("pages_ignorees"),
    }


async def vision_node(state: AgentState, config=None) -> dict:
    """Analyse visuelle multimodale — UN APPEL PAR FICHIER, en parallèle.

    POURQUOI UN APPEL PAR FICHIER, et non un seul qui les porterait tous. Cinq
    photos d'un jardin ne sont pas les cinq pages d'un plan. Réunies dans une
    seule requête, le modèle en fait une moyenne — « une terrasse, de la
    pelouse, un mur » — et l'on perd précisément ce qu'on venait chercher : ce
    que porte CETTE photo-là. Les pages d'un MÊME document, elles, restent
    ensemble : c'est un seul sujet, et une coupe s'explique par son plan.

    Les fichiers partent en parallèle : cinq analyses en série dépassent le
    temps imparti au tour. La porte du fournisseur (`porte_llm`) borne déjà le
    nombre d'appels simultanés — ce n'est donc pas une rafale.

    Dégradation propre si aucun modèle vision n'est configuré.
    """
    pieces = [p for p in (state.get("attachments") or []) if p.get("pages")]
    if not pieces:
        # Chemin hérité : un seul fichier, posé dans les champs au singulier
        # (file d'attente, tâche planifiée, client plus ancien).
        b64 = state.get("attachment_b64")
        if not b64:
            return {"vision_analysis": None}
        pieces = [{"nom": state.get("attachment_name") or "document",
                   "mime": state.get("attachment_mime") or "image/jpeg",
                   "pages": state.get("attachment_pages") or [b64],
                   "pages_totales": state.get("pages_totales"),
                   "pages_ignorees": state.get("pages_ignorees")}]

    from llm.router import get_vision_candidates
    candidats = get_vision_candidates()
    if not candidats:
        return {
            "vision_analysis": None,
            "llm_response": ("Analyse visuelle indisponible : aucun modèle vision configuré. "
                             "Ajoutez une clé Google, Anthropic ou un modèle Groq multimodal."),
            "error": "vision_unavailable",
        }

    demande = state.get("query") or "Décris ce document pour préparer un chiffrage de travaux de sols."
    nombre = len(pieces)

    async def _analyser(rang: int, piece: dict) -> dict:
        """Un fichier, sa cascade de candidats, son analyse — ou sa raison d'échec."""
        nom = piece.get("nom") or "document"
        entete = f"{VISION_PROMPT}\n\nDemande de l'utilisateur : {demande}"
        if nombre > 1:
            # LE MODÈLE DOIT SAVOIR SUR QUOI IL TRAVAILLE. Sans cette phrase,
            # il répond « la photo » à propos de la troisième d'un lot de cinq,
            # et rien dans sa réponse ne permet de les rapprocher ensuite.
            entete += (f"\n\nCeci est le fichier {rang + 1} sur {nombre} joints au même "
                       f"message : « {nom} ». Analyse CELUI-CI seulement — les autres te "
                       "sont soumis séparément, et leurs analyses seront réunies. Ne "
                       "conclus rien sur ce que tu n'as pas sous les yeux.")

        pages = piece.get("pages") or []
        total = piece.get("pages_totales") or 0
        ignorees = piece.get("pages_ignorees") or 0
        if len(pages) > 1:
            entete += (f"\n\nCe document comporte {total or len(pages)} page(s) ; "
                       f"les {len(pages)} premières te sont montrées, dans l'ordre. "
                       "Analyse-les ENSEMBLE : un plan de masse, ses coupes et ses "
                       "façades décrivent le même projet. Dis à quelle page se "
                       "trouve chaque élément que tu relèves.")
        if ignorees:
            entete += (f"\n\nATTENTION : {ignorees} page(s) n'ont PAS été analysées. "
                       "Signale-le dans ta réponse, et ne conclus rien sur ce que tu "
                       "n'as pas vu.")

        mime = piece.get("mime") or "image/jpeg"
        message = HumanMessage(content=[{"type": "text", "text": entete}] + [
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{page}"}}
            for page in pages
        ])

        # LES CANDIDATS SE SUCCÈDENT, comme dans la cascade texte. Un seul essai
        # laissait l'agent aveugle dès que le premier modèle répondait 404 —
        # relevé au banc de recette (« L'analyse visuelle a échoué »).
        derniere = None
        for llm, label in candidats:
            try:
                # Hors cascade : la porte se pose ici aussi, sinon la vision
                # échapperait au plafond du fournisseur.
                from llm.concurrence import porte_llm
                async with porte_llm():
                    response = await llm.ainvoke([message], config=config)
                contenu = response.content
                texte = contenu if isinstance(contenu, str) else str(contenu or "")
                # UNE RÉPONSE VIDE EST UN ÉCHEC, PAS UNE ANALYSE.
                #
                # Relevé en production le 07/09 : après 2 min 23 s d'attente,
                # `openrouter:google/gemini-2.5-pro` a rendu un contenu vide sur
                # une photo de jardin. Le contenu vide était pris pour un
                # succès, la cascade s'arrêtait là, et la personne lisait
                # « Aucune analyse disponible pour ce document » — alors qu'un
                # autre candidat aurait répondu. La cascade TEXTE avait reçu ce
                # correctif le 19/08 (`b553da9`) ; la cascade vision, jamais.
                if not texte.strip():
                    derniere = ValueError("réponse vide")
                    logger.warning("Vision : réponse VIDE de %s sur %s — candidat suivant",
                                   label, nom)
                    continue
                usage = getattr(response, "usage_metadata", None) or {}
                return {"nom": nom, "analyse": texte, "model_used": label,
                        "tokens_in": usage.get("input_tokens", 0),
                        "tokens_out": usage.get("output_tokens", 0)}
            except Exception as e:  # noqa: BLE001 — on passe au suivant
                derniere = e
                logger.warning("Appel vision échoué (%s) sur %s : %s — candidat suivant",
                               label, nom, e)
        return {"nom": nom, "erreur": type(derniere).__name__ if derniere else "inconnu"}

    lus = await asyncio.gather(*[_analyser(i, p) for i, p in enumerate(pieces)])
    reussis = [r for r in lus if r.get("analyse")]

    # Les fichiers que le prétraitement n'a pas su ouvrir : ils ne sont pas
    # partis à la vision, mais la personne les a bien joints — elle doit savoir
    # ce qu'ils sont devenus.
    illisibles = [p for p in (state.get("attachments") or []) if not p.get("pages")]

    if not reussis:
        detail = ", ".join(f"{r['nom']} ({r.get('erreur')})" for r in lus)
        return {
            "vision_analysis": None,
            "llm_response": (f"L'analyse visuelle a échoué ({detail}). "
                             "Réessayez ou joignez une image plus nette."),
            "error": "vision_failed",
        }

    if nombre == 1 and not illisibles:
        analyse = reussis[0]["analyse"]
    else:
        # CHAQUE ANALYSE SOUS LE NOM DE SON FICHIER. C'est ce qui permet, au
        # tour suivant, de dire « la troisième photo » ou « celle du portail »
        # et d'être compris.
        morceaux = [f"## {r['nom']}\n\n{r['analyse']}" for r in reussis]
        rates = [f"{r['nom']} ({r.get('erreur')})" for r in lus if not r.get("analyse")]
        rates += [f"{p.get('nom')} ({p.get('erreur', 'illisible')})" for p in illisibles]
        if rates:
            morceaux.append("## Fichiers non analysés\n\n"
                            + "\n".join(f"- {r}" for r in rates)
                            + "\n\nCe qui suit ne dit rien de ces fichiers-là.")
        analyse = "\n\n".join(morceaux)

    return {
        "vision_analysis": analyse,
        "llm_response": analyse,
        "model_used": reussis[0]["model_used"],
        "tokens_in": sum(int(r.get("tokens_in") or 0) for r in reussis),
        "tokens_out": sum(int(r.get("tokens_out") or 0) for r in reussis),
    }


async def extraction_node(state: AgentState) -> dict:
    """Extraction structurée (JSON) à partir de l'analyse visuelle. Ne jamais inventer."""
    analysis = state.get("vision_analysis")
    if not analysis:
        return {"extracted_data": None}

    llm = get_llm(LLMTier.STANDARD)
    schema = ('{"locaux_zones": [], "revetements_sol": [], "surfaces_m2": {}, '
              '"lineaires_plinthes_ml": {}, "contraintes": [], '
              '"quantites_a_verifier": [], "incertitudes": []}')
    messages = [
        SystemMessage(content=(
            "Tu extrais des données structurées d'une analyse de plan technique BTP "
            "(travaux de sols et revêtements), en vue d'un métré et d'un chiffrage. "
            "Réponds UNIQUEMENT par un objet JSON valide, sans texte autour. "
            "Ne jamais inventer : mets null, [] ou \"non lisible\" pour toute donnée absente.")),
        HumanMessage(content=f"Analyse :\n{analysis}\n\nProduis ce JSON : {schema}"),
    ]
    try:
        response = await llm.ainvoke(messages)
        text = response.content or ""
        match = re.search(r"\{.*\}", text, re.DOTALL)
        data = json.loads(match.group(0)) if match else None
        return {"extracted_data": data}
    except Exception as e:
        logger.warning("Extraction structurée échouée : %s", e)
        return {"extracted_data": None}


async def browser_node(state: AgentState) -> dict:
    """Enrichit le pré-chiffrage avec des prix matériaux actuels (dernier recours)."""
    from browser.tools import web_search

    result = await web_search(
        query=state.get("query", ""),
        user_id=state.get("user_id", ""),
        agent_id="agent2",
        max_results=3,
    )
    existing = list(state.get("raw_chunks") or [])
    if result["success"]:
        existing.append(
            "[SOURCE WEB : prix / données externes, à mentionner et à valider]\n" + result["content"]
        )
    return {
        "raw_chunks": existing,
        "browser_used": True,
        "browser_sources": result.get("sources", []),
        "browser_content": result.get("content"),
        "browser_was_filtered": result.get("was_filtered", False),
    }


async def similar_projects_node(state: AgentState) -> dict:
    """Recherche chantiers/devis similaires via RAG vectoriel."""
    from vectorstore.rag import retrieve_as_context

    contexts = await retrieve_as_context(
        query=state.get("query", "") or (state.get("vision_analysis") or "")[:400],
        user_role=state.get("user_role", "bureau_etudes"),
        source_types=["chantier", "devis", "appel_offre", "cctp", "dpgf"],
        top_k=5,
    )
    existing = list(state.get("raw_chunks") or [])
    existing.extend(contexts)
    return {"raw_chunks": existing}


# ── L'extraction, en blocs d'écran plutôt qu'en accolades ─────────────

# Les clés que la vision rend le plus souvent. Ce n'est PAS une liste fermée :
# ce qui n'est pas reconnu n'est pas affiché du tout, plutôt que reversé en
# accolades faute de mieux.
_CLES_SURFACES = ("surfaces_m2", "surfaces", "surface_m2", "surfaces_m²")
_CLES_POSTES = ("postes_travaux", "postes", "travaux")
_CLES_ELEMENTS = ("elements", "zones", "elements_identifies", "zones_identifiees")

# CE QUI N'EST PAS LISIBLE VAUT CE QUI L'EST — et se perdait.
# La première version de cet affichage ne rendait que les surfaces, les postes
# et les éléments : les réserves de la vision (« cote du muret non lisible »,
# « dénivelé : non lisible ») retournaient au silence, alors qu'elles sont
# exactement ce qui empêche un chiffrage d'être pris pour un devis. Le banc de
# la démo l'a dit tout de suite — « les incertitudes sont dites, pas gommées ».
_CLES_RESERVES = (("contraintes", "À vérifier sur place"),
                  ("incertitudes", "Incertitudes de lecture"),
                  ("reserves", "Réserves"))


def _bloc(type_: str, **champs) -> str:
    """Un bloc d'écran, au format que `MessageRenderer` sait lire."""
    return "```ui\n" + json.dumps({"type": type_, **champs}, ensure_ascii=False) + "\n```"


def _libelle(cle) -> str:
    """« terrasse_bois » -> « Terrasse bois » : la clé technique ne s'affiche pas."""
    mot = str(cle).replace("_", " ").strip()
    return (mot[:1].upper() + mot[1:]) if mot else ""


def _valeur_texte(v) -> str:
    if isinstance(v, (int, float)):
        return f"{v:g}"
    return str(v).strip()


def _blocs_extraction(extracted) -> str:
    """Rend l'extraction de la vision en composants, jamais en JSON.

    LE JSON ÉTAIT RECOPIÉ TEL QUEL DANS LA RÉPONSE. Un pavé d'accolades occupait
    la moitié de l'écran, au-dessus d'un texte français qui disait déjà la même
    chose — relevé en recette le 27/08 sur « analyse ce plan » et sur la question
    d'interconnexion. Personne ne lit des accolades ; le dirigeant à qui on montre
    l'outil y voit une fuite de tuyauterie.

    Ce qui est reconnu devient un tableau ou une liste. Ce qui ne l'est pas n'est
    PAS rendu : l'analyse en prose, juste au-dessus, porte déjà l'information, et
    une extraction inattendue vaut mieux tue qu'en JSON.
    """
    if not isinstance(extracted, dict):
        return ""
    morceaux = []

    for cle in _CLES_SURFACES:
        surfaces = extracted.get(cle)
        if isinstance(surfaces, dict) and surfaces:
            lignes = [[_libelle(k), _valeur_texte(v)] for k, v in surfaces.items()
                      if _valeur_texte(v)]
            if lignes:
                morceaux.append(_bloc("table", titre="Surfaces relevées",
                                      columns=["Poste", "Surface"], rows=lignes))
            break

    for cle in _CLES_POSTES:
        postes = extracted.get(cle)
        if not isinstance(postes, list) or not postes:
            continue
        # Deux formes rencontrées en production : une liste de phrases, ou une
        # liste d'objets (description + quantité + montant) quand la vision a
        # déjà chiffré. Le tableau n'a de sens que dans le second cas.
        if all(isinstance(p, dict) for p in postes):
            lignes = []
            for p in postes:
                desc = _valeur_texte(p.get("description") or p.get("poste") or "")
                qte = next((f"{_valeur_texte(p[k])}" for k in
                            ("surface_m2", "longueur_ml", "quantite", "qte") if p.get(k)), "")
                montant = next((f"{_valeur_texte(p[k])} €" for k in
                                ("montant_euros", "montant", "total") if p.get(k)), "")
                if desc:
                    lignes.append([desc, qte, montant])
            if lignes:
                morceaux.append(_bloc("table", titre="Postes de travaux",
                                      columns=["Poste", "Quantité", "Montant estimé"],
                                      rows=lignes))
        else:
            items = [_valeur_texte(p) for p in postes if _valeur_texte(p)]
            if items:
                morceaux.append(_bloc("list", titre="Postes de travaux", items=items))
        break

    for cle in _CLES_ELEMENTS:
        elements = extracted.get(cle)
        if isinstance(elements, list) and elements:
            items = [_valeur_texte(e) for e in elements if _valeur_texte(e)]
            if items:
                morceaux.append(_bloc("list", titre="Éléments identifiés", items=items))
            break

    for cle, titre in _CLES_RESERVES:
        reserves = extracted.get(cle)
        if isinstance(reserves, list) and reserves:
            items = [_valeur_texte(r) for r in reserves if _valeur_texte(r)]
            if items:
                morceaux.append(_bloc("list", titre=titre, items=items))

    return "\n\n".join(morceaux)


async def prechiffrage_node(state: AgentState) -> dict:
    """Assemble une synthèse + prépare le pré-chiffrage — TOUJOURS validé par un humain."""
    analysis = state.get("vision_analysis")
    extracted = state.get("extracted_data")

    parts = []
    if analysis:
        parts.append(analysis)
    if extracted:
        apercu = _blocs_extraction(extracted)
        if apercu:
            parts.append(apercu)

    # LE TRAVAIL DE RECHERCHE ÉTAIT FAIT, PUIS JETÉ.
    #
    # `similar_projects_node` interroge la mémoire pour trouver les chantiers et
    # devis qui ressemblent à ce plan, et `browser_node` va chercher des prix
    # publics quand la mémoire est vide. Tous deux remplissent `raw_chunks` — que
    # ce nœud-ci, le seul qui écrive la réponse, ne lisait pas. Deux appels
    # payés, deux résultats perdus, et une trame de pré-chiffrage sans le seul
    # élément qui lui donnait de la valeur : « on a déjà fait ça, voilà où ».
    #
    # Les extraits sont bornés et RECOPIÉS TELS QUELS : rien n'est résumé ici,
    # aucun modèle ne repasse derrière ce nœud. Ce qui vient du web porte déjà sa
    # marque depuis `browser_node` ([SOURCE WEB]), elle est conservée.
    comparables = [c for c in (state.get("raw_chunks") or []) if str(c).strip()][:5]
    if comparables:
        parts.append(
            "Chantiers et devis comparables trouvés dans la mémoire de "
            "l'entreprise (à recouper, ce ne sont pas des références de prix) :\n"
            + "\n\n".join(f"- {str(c).strip()[:600]}" for c in comparables))

    summary = "\n\n".join(parts) if parts else (
        state.get("llm_response") or "Aucune analyse disponible pour ce document."
    )

    # L'ANALYSE SE LIT, ELLE NE S'APPROUVE PAS.
    #
    # Ce nœud posait `requires_validation=True` sur TOUT ce qu'il rendait — y
    # compris une simple lecture de plan. L'écran affichait alors « une action
    # attend votre accord », et la personne ne voyait rien de l'analyse avant
    # d'avoir cliqué ; or approuver ne déclenchait rien : aucun chemin ne
    # consomme une validation « prechiffrage ». C'était un accord demandé pour
    # le droit de LIRE — relevé au banc de recette (socle commun).
    #
    # L'agent « ne doit pas valider seul un chiffrage ; il prépare les
    # éléments, la décision finale reste humaine ». Ce qui est garanti ici :
    # rien n'est engagé, rien n'est envoyé, rien n'est créé — l'agent n'en a
    # pas le moyen — et le texte le DIT. Le jour où une approbation aura un
    # effet (créer le devis dans l'outil métier), la porte se posera devant
    # CET effet, pas devant la lecture.
    summary += ("\n\n_Pré-chiffrage indicatif : estimations préparées par l'IA, à "
                "vérifier et valider par un humain avant tout usage commercial. "
                "Rien n'a été envoyé ni engagé._")

    # LA RÉFÉRENCE DE LA PHOTO EST ÉCRITE DANS LA RÉPONSE, à dessein.
    #
    # Une image jointe part toujours ici (le routeur envoie tout ce qui n'a pas
    # de texte extractible à l'agent vision), et cet agent-ci n'appelle aucun
    # skill : il lit, il ne fait pas. La retouche, elle, vit dans le catalogue
    # de l'agent conversationnel — au tour SUIVANT. Écrire la référence dans la
    # réponse la fait entrer dans l'historique du fil, d'où l'autre agent la
    # relira pour appeler `modifier_visuel`. C'est le seul chemin qui ne
    # demande ni table, ni état partagé entre deux graphes.
    # TOUTES LES PHOTOS DU LOT, pas seulement la première (07/09) : un message
    # peut en porter dix, et celle qu'on voudra retoucher n'est pas forcément
    # celle du dessus.
    photos = [(p.get("nom") or "document", p["cle"])
              for p in (state.get("attachments") or []) if p.get("cle")]
    if not photos and state.get("attachment_visuel_cle"):
        photos = [(state.get("attachment_name") or "document",
                   state.get("attachment_visuel_cle"))]
    cle = photos[0][1] if photos else None
    if photos:
        # EN BLOC, PAS SEULEMENT EN TEXTE (03/09). Une référence écrite entre
        # accents graves n'est lue ni par `cles_images_du_fil` (qui cherche
        # `"cle": "…"`) ni par `fichiers_du_fil` (qui cherche des blocs) : au
        # tour suivant, « montre moi la photo » était pris pour une invention
        # et effacé. Le bloc `visuel` fait entrer la photo dans l'historique
        # sous la forme que tous les filets savent lire — et, au passage, la
        # personne VOIT ce que l'assistant a regardé.
        bloc = {"type": "visuel",
                "titre": ("Photo de départ" if len(photos) == 1
                          else f"Les {len(photos)} fichiers reçus"),
                "images": [{"cle": c, "legende": n} for n, c in photos]}
        summary += "\n\n```ui\n" + json.dumps(bloc, ensure_ascii=False) + "\n```"
        if len(photos) == 1:
            summary += (f"\n\n_Photo enregistrée sous la référence `{cle}`. Je peux en "
                        "produire une variante : dites-moi ce que vous voulez changer "
                        "(« remplace la pelouse par une terrasse en bois », « ajoute une "
                        "pergola à droite »), et je garderai le reste à l'identique._")
        else:
            # LES RÉFÉRENCES SONT NOMMÉES UNE À UNE. C'est ce qui permet à
            # l'assistant, au tour suivant, de retoucher « la troisième » ou
            # « toutes » : sans la liste sous les yeux, il n'en connaît qu'une.
            liste = " ; ".join(f"{n} → `{c}`" for n, c in photos)
            summary += (f"\n\n_Les {len(photos)} fichiers sont enregistrés : {liste}. Je "
                        "peux produire une variante de l'un d'eux ou de chacun : dites ce "
                        "que vous voulez changer, et je garderai le reste à l'identique._")

    # CE QUE LA VISION A LU DOIT RESTER DANS LA MÉMOIRE DU FIL.
    #
    # Ce nœud écrit la réponse, l'écran l'affiche, la table `messages` la garde
    # pour le rechargement — mais `state["messages"]` n'était jamais alimenté.
    # Or c'est de LÀ que la mémoire de conversation tire la fenêtre récente. Un
    # tour traité par la vision ne laissait donc RIEN au modèle : au tour
    # suivant, « prépare le pré-devis à partir de ce plan » recevait « je n'ai
    # pas accès à cette analyse », alors que l'analyse était à l'écran, juste
    # au-dessus. Relevé en recette le 27/08 (Q6 puis Q9).
    #
    # Le commentaire de la référence photo, plus haut, PROMETTAIT déjà ce
    # chemin — « elle entre ainsi dans l'historique du fil, d'où l'autre agent
    # la relira » : la promesse portait sur un mécanisme qui n'existait pas.
    #
    # On écrit du texte MASQUÉ, comme agent1 : aucune PII ne dort dans le
    # checkpoint. Le masquage est CPU-bound (spaCy) : il sort de la boucle
    # événementielle. La carte du fil est cumulative — repartir de celle de
    # l'état garde le même jeton pour la même valeur d'un tour à l'autre.
    import asyncio
    from security.anonymizer import anonymizer

    # LA QUESTION AUSSI DOIT ÊTRE MASQUÉE, et c'est ici que ça se joue.
    #
    # Le graphe de la vision n'a AUCUN nœud d'anonymisation — contrairement à
    # celui d'agent1, où `anonymize_node` ouvre le tour. `anonymized_query` y
    # est donc toujours vide, et reprendre la question brute reviendrait à
    # coucher « le plan de M. Untel » dans le checkpoint : exactement ce que le
    # reste du projet s'interdit, et ce que le commentaire d'agent1 promet.
    #
    # Les deux textes passent par le MÊME appel : une même valeur y reçoit le
    # même jeton dans la question et dans l'analyse, et la carte du fil — qui
    # est cumulative — reste exacte pour la réhydratation des tours suivants.
    question = state.get("anonymized_query") or state.get("query") or ""

    # L'EXPERT VISION N'A JAMAIS PROPOSÉ DE SUITE (01/09) : son graphe se
    # termine sur `prechiffrage`, sans `rehydrate_node`. Une analyse de plan
    # restait un cul-de-sac à l'écran, alors que la suite est presque toujours
    # la même — chiffrer, retrouver le dossier, simuler. Les libellés sont fixes
    # et ne citent RIEN du plan : ils n'ont donc pas à être masqués, et
    # `messages` continue de ne porter que `resume_masque`.
    from agents.suggestions import poser as _poser_suites
    from agents.suggestions import suggestions_du_tour
    summary_ecran = _poser_suites(
        summary, suggestions_du_tour(summary, [], expert="agent2"))

    try:
        masques, carte = await asyncio.to_thread(
            anonymizer.anonymize_chunks, [question, summary],
            state.get("entity_map") or {})
        question, resume_masque = masques[0], masques[1]
    except Exception as e:  # noqa: BLE001
        # Une mémoire est un confort, pas une condition : si le masquage tombe,
        # on rend l'analyse sans l'archiver plutôt que de perdre le tour.
        logger.warning("Analyse non mémorisée (masquage indisponible) : %s", e)
        return {
            "final_response": summary_ecran,
            "requires_validation": False,
            "validation_reason": None,
            "validation_payload": None,
        }

    return {
        "final_response": summary_ecran,
        "requires_validation": False,
        "validation_reason": None,
        "validation_payload": None,
        "messages": [HumanMessage(content=question),
                     AIMessage(content=resume_masque)],
        "entity_map": carte,
    }


# ── Edges conditionnels ───────────────────────────────────────────────

# CE QUI FAIT SORTIR SUR LE WEB — et rien d'autre.
# Le navigateur cherche des PRIX publics quand la memoire de l'entreprise n'en
# a pas. Une demande qui ne parle pas d'argent n'a aucune raison de sortir.
_MOTS_CHIFFRAGE = ("chiffr", "prix", "tarif", "cout", "coût", "budget", "devis",
                   "estimation", "estimer", "combien", "euro", "montant")


def should_use_browser(state: AgentState) -> str:
    """Le web, seulement quand la maison ne sait pas ET qu'on parle d'argent.

    DEUX DEFAUTS TENAIENT DANS CETTE ARETE.

    1. L'ORDRE MENTAIT. Le graphe allait « extraction -> browser ->
       similar_projects » : le navigateur passait AVANT la recherche interne.
       `raw_chunks` etait donc vide par construction a ce moment-la, et la
       garde « uniquement si le RAG interne est vide » etait toujours vraie.
       Le dernier recours etait le premier reflexe. L'arete est desormais
       posee APRES `similar_projects`, ce qui rend la condition exacte.

    2. LIRE N'EST PAS CHIFFRER. « Analyse ce plan » partait sur le web et
       revenait avec trois sources, affichees comme telles sous une lecture de
       plan ou elles n'avaient rien a faire. Le navigateur sert a trouver des
       PRIX publics quand la memoire n'en a pas ; il n'a aucun role dans une
       simple description. On ne sort donc que si la demande parle d'argent.

    Releve en recette le 27/08 sur la question 6.
    """
    from config import settings

    if state.get("browser_used"):
        return "prechiffrage"
    if not settings.browser_enabled:
        return "prechiffrage"
    demande = (state.get("query") or "").lower()
    if not any(m in demande for m in _MOTS_CHIFFRAGE):
        return "prechiffrage"
    no_internal = len(state.get("raw_chunks") or []) == 0
    return "browser" if no_internal else "prechiffrage"


# ── Graph ─────────────────────────────────────────────────────────────

def build_agent2_graph():
    graph = StateGraph(AgentState)

    graph.add_node("preprocess", preprocess_attachment_node)
    graph.add_node("vision", vision_node)
    graph.add_node("extraction", extraction_node)
    graph.add_node("browser", browser_node)
    graph.add_node("similar_projects", similar_projects_node)
    graph.add_node("prechiffrage", prechiffrage_node)

    graph.set_entry_point("preprocess")
    graph.add_edge("preprocess", "vision")
    graph.add_edge("vision", "extraction")
    # LA MEMOIRE DE LA MAISON D'ABORD, LE WEB ENSUITE — c'est tout l'objet du
    # correctif : la condition « le RAG interne est vide » ne peut etre vraie
    # que si le RAG a deja parle.
    graph.add_edge("extraction", "similar_projects")
    graph.add_conditional_edges(
        "similar_projects",
        should_use_browser,
        {"browser": "browser", "prechiffrage": "prechiffrage"},
    )
    graph.add_edge("browser", "prechiffrage")
    graph.add_edge("prechiffrage", END)

    return graph.compile()


agent2_graph = build_agent2_graph()

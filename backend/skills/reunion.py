"""
LE COMPTE RENDU DE RÉUNION — une transcription entre, une synthèse courte sort.

LA DEMANDE (03/09, Noa) : « un compte rendu de réunion / synthèse concis, qui
reprend les points clés », déclenchable depuis un raccourci où l'on colle la
transcription.

POURQUOI UN SKILL, ALORS QU'UN MODÈLE SAIT RÉSUMER. Trois raisons, et aucune
n'est théorique :

  1. UNE TRANSCRIPTION NE TIENT PAS DANS UN TOUR. Une heure de réunion fait
     40 000 à 60 000 caractères. Collée dans le chat, elle traverse le budget
     de contexte, le résumé glissant et la coupe des messages longs
     (`memoire_message_max_chars`) : ce qui arrive au modèle est un début et
     une fin. Il résume alors ce qu'il a lu, avec l'aplomb de qui a tout lu.
     Ici la transcription est découpée, chaque part est relevée SÉPARÉMENT,
     puis les relevés sont fondus — et le nombre de passes est DIT.

  2. LA FORME EST LA MOITIÉ DU TRAVAIL. Un compte rendu utile a toujours les
     mêmes rubriques : décisions, actions avec un responsable et une échéance,
     points en suspens. Demandé en prose, on obtient un résumé ; demandé en
     structure, on obtient un relevé sur lequel on peut agir — et l'écran peut
     alors l'afficher mécaniquement (bloc `compte_rendu`), sans dépendre du bon
     vouloir du modèle. La leçon de `terminer_document` (30/08) vaut ici : un
     bloc qui DOIT s'afficher se construit dans le skill.

  3. CE QUI SUIT LE COMPTE RENDU EST DU TRAVAIL D'ASSISTANT. Une fois le relevé
     structuré, le reste s'enchaîne avec les gestes existants : `fichier: true`
     produit le .docx par l'atelier, puis `envoyer_email` l'expédie aux
     participants et `creer_tache_agent` pose les relances. Le skill ne refait
     aucun de ces gestes — il rend une matière sur laquelle ils s'appliquent.

CE QU'IL NE FAIT PAS : inventer. Une action sans responsable nommé garde son
responsable VIDE, une échéance non dite reste vide. Un compte rendu qui
attribue une tâche à quelqu'un qui ne l'a jamais acceptée est pire que pas de
compte rendu du tout — c'est la seule règle qui compte vraiment ici.

Module SOCLE, identique dans les deux projets : seul le vocabulaire des
exemples du catalogue vient du métier, et il vit dans la déclaration.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from skills.erreurs import SkillError

logger = logging.getLogger("duret.skills.reunion")

# ── Les bornes de la CONCISION ───────────────────────────────────────────
# « Concis » est une consigne qu'un modèle interprète ; ce sont ces plafonds
# qui la rendent vraie. Ils coupent APRÈS le modèle, donc une réunion bavarde
# ne produit pas un compte rendu bavard.
MAX_RESUME = 700          # caractères — trois à cinq lignes
MAX_POINTS = 8
MAX_DECISIONS = 8
MAX_ACTIONS = 12
MAX_SUSPENS = 6
MAX_PARTICIPANTS = 20
MAX_LIGNE = 260           # un point de compte rendu est une phrase, pas un paragraphe

# ── Les bornes de la LECTURE ─────────────────────────────────────────────
# Une part par appel. 12 000 caractères ≈ 10 minutes de parole : assez pour
# qu'un sujet ne soit pas coupé en deux, assez peu pour qu'aucun modèle de la
# cascade ne rende un relevé survolé.
TAILLE_PART = 12000
RECOUVREMENT = 400        # on relit la fin de la part précédente : une décision
                          # prise à cheval sur la coupe ne doit pas disparaître
# Au-delà, on traite quand même TOUT ce qui tient et on DIT ce qui a été laissé
# (règle de Noa du 01/09 : une borne se dit, elle ne se subit pas en silence).
MAX_PARTS = 40
# Trois relevés de front : la porte de `llm/concurrence.py` gouverne le reste,
# et un compte rendu n'a pas à prendre tous les créneaux du fournisseur.
PARTS_DE_FRONT = 3


CONSIGNE_PART = """Tu relèves les faits d'un EXTRAIT de transcription de réunion (partie {i} sur {n}).

NE RÉSUME PAS, NE CONCLUS PAS : relève. Une autre passe fera la synthèse.
Ne relève QUE ce qui est dit dans cet extrait. N'invente aucun nom, aucune date,
aucun chiffre. Si un point est coupé en début ou fin d'extrait, relève-le tel quel.

Réponds UNIQUEMENT par un objet JSON, sans commentaire :
{{"participants": ["prénom ou nom cité comme prenant la parole"],
  "points": ["fait, information ou position exprimée"],
  "decisions": ["ce qui a été TRANCHÉ, pas ce qui a été évoqué"],
  "actions": [{{"quoi": "ce qui est à faire", "qui": "la personne nommée, sinon vide", "quand": "l'échéance dite, sinon vide"}}],
  "en_suspens": ["question laissée ouverte, désaccord, information manquante"]}}

Reprends les chiffres, montants, dates et références EXACTEMENT comme ils sont dits.

EXTRAIT :
{extrait}"""


CONSIGNE_SYNTHESE = """Tu rédiges le compte rendu FINAL d'une réunion, à partir des relevés bruts de ses {n} partie(s).

CE QUI FAIT UN BON COMPTE RENDU, dans l'ordre :
- CONCIS. Le résumé fait 3 à 5 lignes ({maxi} caractères au maximum) et répond à : de quoi a-t-on parlé, qu'est-ce qui en sort.
- FUSIONNÉ. Un même sujet revenu trois fois dans la réunion donne UN point, pas trois.
- HIÉRARCHISÉ. Le plus engageant d'abord : ce qui est décidé, puis ce qui est à faire, puis le reste.
- SANS INVENTION. Une action dont personne n'a pris la charge garde "qui" VIDE ; une échéance non dite garde "quand" VIDE. Ne devine JAMAIS un responsable ni une date : un compte rendu qui attribue une tâche à quelqu'un qui ne l'a pas acceptée fait plus de dégâts qu'un compte rendu incomplet.
- FIDÈLE AUX CHIFFRES. Montants, quantités, dates et références se recopient à l'identique.

Distingue franchement une DÉCISION (c'est tranché, on avance) d'un POINT CLÉ (c'est dit, c'est utile à savoir) et d'un POINT EN SUSPENS (ce n'est pas réglé).
{focus}
Réponds UNIQUEMENT par un objet JSON, sans commentaire :
{{"titre": "un titre court de réunion, sans date",
  "participants": ["les personnes citées"],
  "resume": "3 à 5 lignes",
  "points_cles": ["au plus {points} points"],
  "decisions": ["au plus {decisions}"],
  "actions": [{{"quoi": "...", "qui": "...", "quand": "..."}}],
  "en_suspens": ["au plus {suspens}"]}}

RELEVÉS :
{releves}"""


def _texte(v) -> str:
    return re.sub(r"\s+", " ", str(v if v is not None else "")).strip()


def _lignes(v, maxi: int) -> list[str]:
    """Une liste de phrases propres, dédoublonnée, bornée.

    Le dédoublonnage est fait ICI et pas laissé au modèle : sur une réunion où
    le même sujet revient trois fois, les relevés de trois parts différentes
    rendent trois formulations voisines, et « fusionne » est précisément la
    consigne qu'un modèle applique le moins bien.
    """
    sorties: list[str] = []
    vus: set[str] = set()
    for element in (v if isinstance(v, list) else []):
        ligne = _texte(element)[:MAX_LIGNE]
        if not ligne:
            continue
        cle = re.sub(r"[^a-z0-9]", "", ligne.lower())[:80]
        if cle in vus:
            continue
        vus.add(cle)
        sorties.append(ligne)
        if len(sorties) >= maxi:
            break
    return sorties


def _actions(v, maxi: int) -> list[dict]:
    """Les actions, responsable et échéance VIDES quand ils n'ont pas été dits."""
    sorties: list[dict] = []
    vus: set[str] = set()
    for element in (v if isinstance(v, list) else []):
        if isinstance(element, str):
            element = {"quoi": element}
        if not isinstance(element, dict):
            continue
        quoi = _texte(element.get("quoi") or element.get("action"))[:MAX_LIGNE]
        if not quoi:
            continue
        cle = re.sub(r"[^a-z0-9]", "", quoi.lower())[:80]
        if cle in vus:
            continue
        vus.add(cle)
        qui = _texte(element.get("qui") or element.get("responsable"))[:60]
        quand = _texte(element.get("quand") or element.get("echeance"))[:60]
        # Un modèle qui n'a pas de responsable écrit volontiers « à définir »,
        # « TBD », « non précisé » : c'est la même chose que vide, et un champ
        # vide se voit à l'écran comme un trou à combler.
        if re.fullmatch(r"(à |a )?(définir|definir|preciser|préciser|determiner|déterminer)|tbd|n/?a|non précisé|non precise|inconnu|-+",
                        qui.lower().strip()):
            qui = ""
        if re.fullmatch(r"(à |a )?(définir|definir|preciser|préciser)|tbd|n/?a|non précisé|non precise|-+",
                        quand.lower().strip()):
            quand = ""
        sorties.append({"quoi": quoi, "qui": qui, "quand": quand})
        if len(sorties) >= maxi:
            break
    return sorties


def decouper(transcription: str) -> list[str]:
    """La transcription en parts qui se recouvrent, coupées AUX RESPIRATIONS.

    On cherche une fin de ligne ou de phrase dans le dernier dixième de la
    part : couper au milieu d'une réplique fait perdre au relevé de quoi elle
    parlait. Le recouvrement rattrape ce qui reste à cheval.

    Fonction pure — c'est elle que le banc exerce sur une transcription doublée.
    """
    texte = (transcription or "").strip()
    if not texte:
        return []
    if len(texte) <= TAILLE_PART:
        return [texte]

    parts: list[str] = []
    debut = 0
    while debut < len(texte) and len(parts) < MAX_PARTS:
        fin = min(debut + TAILLE_PART, len(texte))
        if fin < len(texte):
            fenetre = texte[debut + int(TAILLE_PART * 0.9):fin]
            coupe = max(fenetre.rfind("\n"), fenetre.rfind(". "))
            if coupe > 0:
                fin = debut + int(TAILLE_PART * 0.9) + coupe + 1
        # Les parts ne sont PAS rognées : ce sont des tranches exactes du
        # texte, et c'est ce qui permet à `couvert()` de dire jusqu'où on a
        # vraiment lu — donc de ne jamais laisser croire qu'on a tout lu.
        parts.append(texte[debut:fin])
        if fin >= len(texte):
            break
        debut = max(fin - RECOUVREMENT, debut + 1)
    return parts


def couvert(transcription: str, parts: list[str]) -> int:
    """Jusqu'où les parts ont réellement lu — le recouvrement ne compte pas deux fois.

    Sert à une seule chose, mais elle est essentielle : savoir si la
    transcription a été lue EN ENTIER. Sommer les longueurs mentirait (les
    parts se recouvrent), et un compte rendu bâti sur les trois quarts d'une
    réunion sans le dire est exactement le défaut qu'on cherche à éviter.
    """
    texte = (transcription or "").strip()
    if not parts:
        return 0
    fin = parts[-1]
    pos = texte.rfind(fin[-200:] if len(fin) > 200 else fin)
    return len(texte) if pos < 0 else min(len(texte), pos + len(fin[-200:] if len(fin) > 200 else fin))


def _json_de(brut: str) -> dict:
    """Le premier objet JSON d'une réponse de modèle. Tolérant aux enrobages."""
    texte = str(brut or "")
    # Un modèle enrobe volontiers son JSON dans une clôture ```json.
    trouve = re.search(r"\{.*\}", texte, re.S)
    if not trouve:
        raise SkillError("Le modèle n'a pas rendu de relevé exploitable. Réessayez.")
    try:
        return json.loads(trouve.group(0))
    except json.JSONDecodeError:
        # Une virgule de trop en fin d'objet suffit à tout perdre : on retente
        # une fois après l'avoir retirée, plutôt que de jeter le travail.
        recolle = re.sub(r",\s*([}\]])", r"\1", trouve.group(0))
        try:
            return json.loads(recolle)
        except json.JSONDecodeError as e:
            raise SkillError(f"Le relevé du modèle est illisible : {e}")


async def _appeler(invite: str, palier: str) -> str:
    from langchain_core.messages import HumanMessage
    from llm.router import LLMTier, get_llm
    reponse = await get_llm(LLMTier(palier)).ainvoke([HumanMessage(content=invite)])
    return str(getattr(reponse, "content", "") or "")


async def _relever(extrait: str, i: int, n: int, verrou) -> dict:
    """Le relevé d'UNE part. Une part qui échoue ne perd pas les autres."""
    async with verrou:
        try:
            brut = await _appeler(
                CONSIGNE_PART.format(i=i, n=n, extrait=extrait), "standard")
            return _json_de(brut)
        except Exception as e:  # noqa: BLE001
            logger.warning("Relevé de la partie %s/%s perdu : %s", i, n, e)
            return {}


def _fondre(releves: list[dict]) -> str:
    """Les relevés des parts en une matière lisible pour la passe de synthèse."""
    morceaux = []
    for i, r in enumerate(releves, 1):
        if not isinstance(r, dict) or not r:
            continue
        lignes = [f"--- partie {i}"]
        for cle, titre in (("decisions", "DÉCISIONS"), ("points", "POINTS"),
                           ("en_suspens", "EN SUSPENS")):
            valeurs = [_texte(x)[:MAX_LIGNE] for x in (r.get(cle) or []) if _texte(x)]
            if valeurs:
                lignes.append(titre + " : " + " | ".join(valeurs))
        actions = []
        for a in (r.get("actions") or []):
            if isinstance(a, dict) and _texte(a.get("quoi")):
                actions.append(f"{_texte(a.get('quoi'))}"
                               f" (qui: {_texte(a.get('qui')) or '?'},"
                               f" quand: {_texte(a.get('quand')) or '?'})")
            elif isinstance(a, str) and a.strip():
                actions.append(_texte(a))
        if actions:
            lignes.append("ACTIONS : " + " | ".join(actions))
        gens = [_texte(x) for x in (r.get("participants") or []) if _texte(x)]
        if gens:
            lignes.append("PARTICIPANTS : " + ", ".join(gens))
        if len(lignes) > 1:
            morceaux.append("\n".join(lignes))
    return "\n".join(morceaux)


def construire_bloc(cr: dict, titre: str, sous_titre: str) -> dict:
    """Le bloc d'écran, construit MÉCANIQUEMENT depuis le compte rendu.

    Jamais recopié par le modèle : c'est la leçon de `fd1bcf7` et de
    `skills/affichage.py`. Fonction pure, exercée au banc.
    """
    bloc = {"type": "compte_rendu", "titre": titre, "resume": cr.get("resume", "")}
    if sous_titre:
        bloc["sous_titre"] = sous_titre
    if cr.get("participants"):
        bloc["participants"] = cr["participants"]
    sections = []
    for cle, libelle in (("decisions", "Décisions"), ("points_cles", "Points clés"),
                         ("en_suspens", "Points en suspens")):
        if cr.get(cle):
            sections.append({"titre": libelle, "items": cr[cle]})
    if sections:
        bloc["sections"] = sections
    if cr.get("actions"):
        bloc["actions"] = cr["actions"]
    return bloc


def _entete(data: dict) -> tuple[str, str]:
    """Le titre du compte rendu et sa ligne de contexte."""
    titre = _texte(data.get("titre"))[:120]
    date = _texte(data.get("date"))[:40]
    if not date:
        date = datetime.now(timezone.utc).astimezone().strftime("%d/%m/%Y")
    return titre, date


async def _en_document(cr: dict, titre: str, date: str, user) -> Optional[dict]:
    """Le compte rendu en .docx, produit par l'atelier. Rend son bloc `fichier`.

    Mécanique de bout en bout : le modèle n'écrit pas une ligne du document, il
    ne fait que demander `fichier: true`. Un échec de production ne perd pas le
    compte rendu — il reste à l'écran, et on le dit.
    """
    from bureautique.atelier import ajouter, ouvrir, terminer
    proprio = str(getattr(user, "id", "") or "")
    entete = {"titre": titre, "sous_titre": date, "format": "docx"}

    elements: list[dict] = []
    if cr.get("participants"):
        elements.append({"type": "paragraphe",
                         "texte": "Participants : " + ", ".join(cr["participants"])})
    if cr.get("resume"):
        elements.append({"type": "titre", "texte": "Résumé", "niveau": 1})
        elements.append({"type": "paragraphe", "texte": cr["resume"]})
    for cle, libelle in (("decisions", "Décisions"), ("points_cles", "Points clés"),
                         ("en_suspens", "Points en suspens")):
        if cr.get(cle):
            elements.append({"type": "titre", "texte": libelle, "niveau": 1})
            elements.append({"type": "liste", "items": cr[cle]})
    if cr.get("actions"):
        elements.append({"type": "titre", "texte": "Actions", "niveau": 1})
        elements.append({"type": "tableau",
                         "entetes": ["Action", "Responsable", "Échéance"],
                         "lignes": [[a.get("quoi", ""), a.get("qui", "") or "à désigner",
                                     a.get("quand", "") or "à fixer"]
                                    for a in cr["actions"]]})

    def _produire():
        jeton = ouvrir(entete, proprio)
        ajouter(jeton, elements, proprio)
        return jeton, terminer(jeton, proprio)

    try:
        jeton, fiche = await asyncio.to_thread(_produire)
    except Exception as e:  # noqa: BLE001
        logger.warning("Document du compte rendu impossible : %s", e)
        return None
    nom = re.sub(r"[^\w\-. ]", "", titre).strip().replace(" ", "-")[:60] or "compte-rendu"
    return {"type": "fichier", "url": f"/api/documents/{jeton}", "nom": f"{nom}.docx",
            "titre": titre, "format": "docx", "octets": fiche.get("octets")}


def _sans_entete(texte: str) -> str:
    """La transcription seule, quand elle arrive collée sous une consigne.

    Le raccourci du menu éclair préremplit « … Transcription : » et l'on colle
    la réunion dessous ; le serveur passe alors le message ENTIER (jeton
    `@message`). Ces trois lignes de consigne ne sont pas de la réunion : les
    laisser ferait relever au modèle des « décisions » qui sont en fait les
    instructions de l'utilisateur.

    Prudent par construction : on ne coupe que s'il reste une vraie
    transcription derrière. Fonction pure, exercée au banc.
    """
    texte = (texte or "").strip()
    for marque in ("transcription :", "transcription:", "compte rendu :",
                   "verbatim :", "retranscription :"):
        position = texte.lower().rfind(marque)
        if position >= 0:
            reste = texte[position + len(marque):].strip()
            if len(reste) >= 200:
                return reste
    return texte


async def compte_rendu_reunion(data: dict, user) -> dict:
    """Une transcription entre, un compte rendu court et structuré sort."""
    transcription = _sans_entete(str(data.get("transcription") or data.get("texte")
                                     or data.get("contenu") or ""))
    if len(transcription) < 200:
        # Sous ce seuil, ce n'est pas une réunion : c'est une phrase collée par
        # erreur, ou le modèle qui a oublié de passer le texte. Le dire vaut
        # mieux que rendre un compte rendu de trois mots.
        raise SkillError(
            "La transcription est trop courte pour un compte rendu. Collez le texte "
            "de la réunion (ou ouvrez la pièce jointe qui le contient), puis redemandez.")

    from security.anonymizer import anonymizer

    titre_demande, date = _entete(data)
    focus = _texte(data.get("focus") or data.get("objectif"))[:300]
    veut_fichier = str(data.get("fichier") or "").strip().lower() in (
        "1", "true", "oui", "vrai", "docx", "word", "fichier")

    parts = decouper(transcription)
    caracteres_lus = couvert(transcription, parts)
    tout_lu = caracteres_lus >= len(transcription.strip())

    # ── Masquage AVANT le modèle, réhydratation APRÈS ────────────────────
    # Une transcription est le texte le plus chargé en noms de toute
    # l'application. On passe donc par le même contrat que les skills mail :
    # si l'anonymisation est active, rien de nominatif ne part chez le
    # fournisseur ; si elle est coupée (défaut depuis le 31/08), l'appel est
    # transparent. Une seule carte pour toutes les parts — sans quoi [PER_1]
    # ne désignerait pas la même personne d'une part à l'autre.
    masques, carte = await asyncio.to_thread(anonymizer.anonymize_chunks, parts, {})

    verrou = asyncio.Semaphore(PARTS_DE_FRONT)
    if len(masques) == 1:
        releves = [await _relever(masques[0], 1, 1, verrou)]
    else:
        releves = list(await asyncio.gather(
            *[_relever(p, i, len(masques), verrou) for i, p in enumerate(masques, 1)]))
    if not any(releves):
        raise SkillError("Aucun relevé n'a abouti sur cette transcription. "
                         "Réessayez, ou découpez la réunion en deux demandes.")

    matiere = _fondre(releves)
    # Palier COMPLEX : fondre des relevés contradictoires, hiérarchiser et
    # distinguer une décision d'une intention est un travail de jugement. Le
    # palier rapide rend une liste à plat.
    brut = await _appeler(CONSIGNE_SYNTHESE.format(
        n=len(masques), maxi=MAX_RESUME, points=MAX_POINTS,
        decisions=MAX_DECISIONS, suspens=MAX_SUSPENS,
        focus=(f"\nL'utilisateur demande d'insister sur : {focus}\n" if focus else ""),
        releves=matiere[:60000]), "complex")
    sortie = _json_de(brut)

    cr = {
        "resume": _texte(sortie.get("resume"))[:MAX_RESUME],
        "points_cles": _lignes(sortie.get("points_cles"), MAX_POINTS),
        "decisions": _lignes(sortie.get("decisions"), MAX_DECISIONS),
        "actions": _actions(sortie.get("actions"), MAX_ACTIONS),
        "en_suspens": _lignes(sortie.get("en_suspens"), MAX_SUSPENS),
        "participants": _lignes(sortie.get("participants"), MAX_PARTICIPANTS),
    }
    titre = titre_demande or _texte(sortie.get("titre"))[:120] or "Compte rendu de réunion"

    # Réhydratation : le compte rendu que des humains liront porte les VRAIS
    # noms. Un jeton resté orphelin n'a rien à faire dans un document remis à
    # des participants (leçon d'`ec2553d`) : il devient un trou visible.
    def _rendre(v):
        if isinstance(v, str):
            return re.sub(r"\[[A-Z]+_\d+\]", "[à compléter]",
                          anonymizer.rehydrate(v, carte))
        if isinstance(v, list):
            return [_rendre(x) for x in v]
        if isinstance(v, dict):
            return {k: _rendre(x) for k, x in v.items()}
        return v

    cr = _rendre(cr)
    if not cr["resume"] and not cr["decisions"] and not cr["points_cles"]:
        raise SkillError("Le compte rendu est revenu vide. Vérifiez que le texte collé "
                         "est bien la transcription de la réunion.")

    contexte = [f"{len(cr['participants'])} participant(s)"] if cr["participants"] else []
    contexte.append(f"{len(cr['actions'])} action(s)" if cr["actions"] else "aucune action")
    if len(parts) > 1:
        contexte.append(f"{len(parts)} parties lues")
    sous_titre = date + " · " + " · ".join(contexte)

    blocs: list[dict] = [construire_bloc(cr, titre, sous_titre)]
    fichier = await _en_document(cr, titre, date, user) if veut_fichier else None
    if fichier:
        blocs.append(fichier)

    reste = len(transcription) - caracteres_lus
    message = f"Compte rendu de « {titre} » : {sous_titre}."
    if not tout_lu and reste > 0:
        message += (f" Attention : la transcription dépasse ce qu'une seule demande "
                    f"peut lire ({caracteres_lus} caractères traités sur "
                    f"{len(transcription)}) — collez la fin dans une seconde demande.")
    if veut_fichier and not fichier:
        message += " Le document Word n'a pas pu être produit ; le compte rendu reste à l'écran."

    return {
        "titre": titre,
        "parties_lues": len(parts),
        "actions": len(cr["actions"]),
        # LE CONTENU NE VOYAGE QU'UNE FOIS : il vit dans le bloc, que le modèle
        # voit aussi. Le porter en double gonflait le résultat jusqu'à le faire
        # couper au milieu de son JSON (leçon du 01/09, `_blocs_garantis`).
        "bloc_ui": blocs if len(blocs) > 1 else blocs[0],
        "bloc_garanti": True,
        "message_final": message,
        "a_faire": (
            "Le compte rendu est DÉJÀ affiché par un bloc mécanique : ne le recopie "
            "pas, n'écris aucun bloc pour lui. Dis une ou deux phrases sur ce qui "
            "ressort de la réunion (la décision principale, ou ce qui reste ouvert). "
            "Puis, SI c'est utile, propose la suite en UNE ligne — sans la faire "
            "sans accord : produire le Word (rappelle ce skill avec `fichier: true`), "
            "l'envoyer aux participants (`envoyer_email`), ou poser une relance sur "
            "une action datée (`creer_tache_agent`). "
            "Une action dont le responsable ou l'échéance est vide n'est PAS une "
            "erreur : c'est ce que la réunion n'a pas tranché — signale-le plutôt "
            "que de le combler."),
    }


# La déclaration vit avec le skill : le cœur vient la lire (`skills/registre.py`).
from skills.registre import Declaration  # noqa: E402

SKILLS = {
    "compte_rendu_reunion": Declaration(
        fonction=compte_rendu_reunion,
        description=(
            "COMPTE RENDU DE REUNION : transforme une transcription (notes prises "
            "au fil de l'eau, retranscription d'enregistrement, echange colle dans "
            "le chat) en une synthese COURTE et structuree — resume en quelques "
            "lignes, points cles, decisions, actions avec responsable et echeance, "
            "points en suspens. A appeler des qu'on dit « fais le compte rendu de "
            "cette reunion », « synthetise cet echange », « resume-moi ce point ». "
            "`transcription` : QUAND LA REUNION EST COLLEE DANS LE MESSAGE, ecris "
            "exactement `\"transcription\": \"@message\"` — le serveur y mettra le "
            "message entier. NE RECOPIE JAMAIS une longue transcription toi-meme : "
            "tu la raccourcirais, et le compte rendu porterait sur la moitie de la "
            "reunion. Quand le texte vient d'un fichier, passe ce que "
            "`lire_piece_jointe` / `nas_lire` / `drive_lire_lot` t'a rendu, sans le "
            "raccourcir non plus — le skill decoupe et lit TOUT. `titre`, `date`, "
            "`focus` (« insiste sur le budget ») sont optionnels. `fichier: true` "
            "produit en plus le document Word, pret a etre envoye. Le compte rendu "
            "s'affiche AUTOMATIQUEMENT : ne le recopie pas. Ensuite seulement, et "
            "seulement si on le demande, enchaine `envoyer_email` ou "
            "`creer_tache_agent`"),
        requis=["transcription"],
        optionnels=["titre", "date", "focus", "fichier"],
        # Rien ne sort de l'entreprise : on lit un texte et on rend une synthèse.
        # Le document produit reste dans l'atelier, comme pour `liste_clients`.
        effet="lecture",
        libelle="je fais le compte rendu"),
}

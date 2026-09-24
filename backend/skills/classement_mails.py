"""
CLASSER LES MAILS DANS LES DOSSIERS DE LA BOÎTE (24/09, Duret).

Conversation de Damien, 23/09 : « trie les mails, associe chaque mail à un dossier,
classe-les » → l'assistant listait, proposait des catégories… et s'arrêtait là.
RIEN ne savait écrire dans la boîte. Ce geste est le bras qui manquait ; la tête
reste au modèle, et c'est voulu (Noa : « rien de déterministe ») :

  1. le modèle LISTE les mails (`lire_mails`, tous, quel que soit leur nombre) et
     les dossiers existants (`dossiers_mail`) ;
  2. il DÉCIDE, mail par mail, du dossier — par affaire, par responsable, par
     sujet : c'est son jugement, aucune règle ici ;
  3. il appelle `classer_mails` avec sa proposition. L'effet est EXTERNE : la
     carte d'accord montre le tableau complet « mail → dossier », la personne
     lit, corrige si besoin (« non, celui-là dans X »), approuve ;
  4. à l'accord, CE geste déplace les messages, crée les dossiers manquants,
     et rend ce qui est parti et ce qui a échoué — un tableau garanti, lisible.

Sur la messagerie de Duret (une boîte Gmail par IMAP), un dossier est un libellé :
déplacer un message le sort de la réception et le range sous le libellé. Le
dépôt sur le NAS n'est pas ici : c'est `nas_deposer`, avec le fichier voulu.
"""
from __future__ import annotations

import asyncio
import logging

from skills.erreurs import SkillError
from skills.registre import Declaration

logger = logging.getLogger("duret.skills.classement_mails")

MAX_MAILS_PAR_GESTE = 1000
LONGUEUR_DOSSIER = 120


def lire_affectations(data: dict) -> list[dict]:
    """Les couples (ref, dossier) tels que le modèle les écrit, ramenés à UNE forme.

    Le modèle écrit tantôt `classement: [{ref, dossier}]`, tantôt `mails`, `affectations`,
    ou un dictionnaire `{dossier: [refs]}` : refuser pour un nom de champ est le piège
    déjà payé avec `url` (30/08). Fonction PURE, jouée au banc."""
    brut = (data.get("classement") or data.get("affectations") or data.get("mails")
            or data.get("repartition") or data.get("plan") or [])
    couples: list[dict] = []
    if isinstance(brut, dict):
        for dossier, refs in brut.items():
            for r in (refs if isinstance(refs, list) else [refs]):
                couples.append({"ref": r, "dossier": dossier})
    elif isinstance(brut, list):
        for item in brut:
            if isinstance(item, dict):
                couples.append({"ref": item.get("ref") or item.get("reference") or item.get("id") or item.get("mail"),
                                "dossier": item.get("dossier") or item.get("libelle") or item.get("cible")
                                or item.get("affaire") or item.get("categorie"),
                                "objet": item.get("objet") or ""})
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                couples.append({"ref": item[0], "dossier": item[1]})
    propres = []
    for c in couples:
        ref = " ".join(str(c.get("ref") or "").split())
        dossier = " ".join(str(c.get("dossier") or "").split())[:LONGUEUR_DOSSIER].strip("/ ")
        if ref and dossier:
            propres.append({"ref": ref, "dossier": dossier, "objet": str(c.get("objet") or "")[:120]})
    return propres[:MAX_MAILS_PAR_GESTE]


def bloc_du_classement(data: dict) -> dict:
    """Le tableau « mail → dossier » montré AVANT l'accord, construit depuis les
    arguments dont l'empreinte est vérifiée : ce qui est lu est ce qui sera fait."""
    couples = lire_affectations(data)
    lignes = []
    for c in couples:
        # L'objet vient des arguments (le catalogue le demande) ; sans lui, la
        # référence — jamais une lecture de la boîte au moment de l'aperçu.
        lignes.append([c.get("objet") or c["ref"], c["dossier"]])
    par_dossier: dict[str, int] = {}
    for c in couples:
        par_dossier[c["dossier"]] = par_dossier.get(c["dossier"], 0) + 1
    return {"type": "table", "titre": f"Classement proposé ({len(lignes)} mail(s), {len(par_dossier)} dossier(s))",
            "columns": ["Mail", "Dossier"], "rows": lignes}


async def classer_mails(data: dict, user) -> dict:
    from mail.authorization import verifier_acces
    from mail.lecture import fournisseur, _resoudre
    from mail.skills import _boite_a_lire

    couples = lire_affectations(data)
    if not couples:
        raise SkillError("Donne `classement`: une liste de {\"ref\": <ref du mail>, \"dossier\": <nom du dossier>}"
                         " — les `ref` viennent de `lire_mails`, les dossiers de `dossiers_mail` ou de ton choix.")
    cible = await _boite_a_lire(data, user)
    boite = await verifier_acces(user, cible)
    if fournisseur() != "imap":
        raise SkillError("Le classement dans les dossiers n'est disponible que sur une boîte lue par IMAP "
                         "(la boîte de l'entreprise). Cette messagerie ne le permet pas encore.")
    from mail import imap

    par_dossier: dict[str, list[dict]] = {}
    inconnues = []
    for c in couples:
        ident = _resoudre(c["ref"], boite)
        if not ident:
            inconnues.append(c)
            continue
        par_dossier.setdefault(c["dossier"], []).append({**c, "identifiant": ident})

    deplaces, echecs, crees = [], [], []
    for dossier, lot in par_dossier.items():
        try:
            bilan = await asyncio.to_thread(imap.deplacer, boite, [x["identifiant"] for x in lot], dossier,
                                            bool(data.get("creer_dossiers", True)))
        except Exception as e:  # noqa: BLE001 — un dossier en échec n'arrête pas les autres
            logger.warning("Classement vers « %s » impossible : %s", dossier, str(e)[:160])
            echecs += [{**x, "raison": str(e)[:160]} for x in lot]
            continue
        if bilan.get("dossier_cree"):
            crees.append(dossier)
        partis = set(bilan.get("deplaces") or [])
        raisons = dict(bilan.get("echecs") or [])
        for x in lot:
            if x["identifiant"] in partis:
                deplaces.append(x)
            else:
                echecs.append({**x, "raison": raisons.get(x["identifiant"], "non déplacé")})
    for c in inconnues:
        echecs.append({**c, "raison": "référence inconnue (relis les mails avec lire_mails)"})

    lignes = [[x.get("objet") or x["ref"], x["dossier"], "classé"] for x in deplaces] + \
             [[x.get("objet") or x["ref"], x["dossier"], "ÉCHEC : " + x["raison"]] for x in echecs]
    bloc = {"type": "table", "titre": f"Classement fait ({len(deplaces)} mail(s) rangé(s), {len(echecs)} en échec)",
            "columns": ["Mail", "Dossier", "Résultat"], "rows": lignes}
    phrase = (f"{len(deplaces)} mail(s) rangé(s) dans {len(par_dossier)} dossier(s)"
              + (f", {len(crees)} dossier(s) créé(s) : {', '.join(crees[:8])}" if crees else "")
              + (f" ; {len(echecs)} n'ont pas pu être déplacé(s)." if echecs else "."))
    return {"ok": bool(deplaces) or not echecs, "deplaces": len(deplaces), "echecs": len(echecs),
            "dossiers_crees": crees, "message_final": phrase, "bloc_garanti": True, "bloc_ui": [bloc],
            "a_faire": ("Le tableau du classement S'AFFICHE AUTOMATIQUEMENT : ne le recopie pas. Dis en une "
                        "phrase ce qui a été rangé, nomme les dossiers créés, et pour chaque échec dis pourquoi. "
                        "Ne rappelle pas ce geste pour les mêmes mails.")}


SKILLS = {
    "classer_mails": Declaration(
        fonction=classer_mails,
        description=(
            "RANGE des mails dans les DOSSIERS de la boîte (« trie mes mails », « classe-les par "
            "affaire / par responsable », « mets chaque mail dans son dossier »). C'est TOI qui décides "
            "du dossier de chaque mail : lis-les d'abord (`lire_mails`, tous — non lus, période…), "
            "regarde les dossiers existants (`dossiers_mail`), puis passe `classement`: "
            "[{\"ref\": <ref du mail>, \"dossier\": <nom du dossier>, \"objet\": <objet>}] pour TOUS les mails "
            "visés, même cent. Un dossier absent est créé (`creer_dossiers: false` pour l'interdire). "
            "La personne voit le tableau mail → dossier et donne son accord AVANT tout déplacement : "
            "propose donc directement ce geste, ne demande pas confirmation par une question. "
            "`mailbox` pour une autre boîte. Rien n'est supprimé : un mail déplacé reste dans la boîte."),
        requis=["classement"],
        optionnels=["mailbox", "creer_dossiers"],
        effet="externe", libelle="je range les mails dans leurs dossiers"),
}

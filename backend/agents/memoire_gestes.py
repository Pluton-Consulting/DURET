"""
LA MÉMOIRE DES GESTES DU TOUR — ce que le modèle a déjà fait, dit en une ligne.

LE DÉFAUT QUE CE MODULE FERME (export Langfuse du 14/09, fil c9f5a00d). À
chaque passe de la boucle d'actions, le modèle reçoit un prompt NEUF : ses
propres blocs ```action des passes précédentes n'y sont pas, et les résultats
lui parvenaient SANS leurs arguments (« il les a déjà écrits, les lui renvoyer
serait les payer deux fois »). Or il ne les a PAS sous les yeux : il les a
écrits dans un appel qui n'existe plus. Ce qu'il voyait :

    {"skill": "ajouter_document", "resultat_masque": "{… \"ajoutes\": 6,
     \"total\": 269, \"note\": \"6 élément(s) ajouté(s). Continue d'ajouter…\"}"}

— et rien de ce qu'il avait versé. Chaque passe ressemblait donc à la première,
et il reversait le devis : 159 `ajouter_document` en trente et une minutes, 911
blocs, le même en-tête « Devis N° DV0001451 » réécrit à chaque fois. Même
mécanique, en plus court, à 14:56 : quatre `reproduire_document` avec la même
table, parce que rien ne lui disait qu'il l'avait déjà essayée.

LE PRINCIPE : le modèle relit son JOURNAL, pas ses arguments bruts. Une ligne
par geste — le skill, l'essentiel de ce qu'il a demandé, l'issue — assez pour
reconnaître « je l'ai déjà fait », pas assez pour payer deux fois un document
entier. Les éléments versés dans un document se résument à leur type et au
début de leur texte : c'est ce qui permet de voir « titre « Devis N°
DV0001451 » » revenir, et de s'arrêter.

Module PUR : aucun import du projet, le banc l'exerce tel quel.
"""
from __future__ import annotations

import json

# Ce qu'une ligne peut peser. Au-delà, le journal d'un tour de 120 gestes
# deviendrait lui-même le mur qu'il est censé remplacer.
MAX_LIGNE = 260
MAX_TEXTE = 70
MAX_ELEMENTS = 4
BUDGET_ELEMENTS = 130
MAX_LIGNES_JOURNAL = 60
# Les clés qui ne disent rien au modèle de ce qu'il a fait.
_CLES_MUETTES = frozenset({"_fil", "payload_hash"})


def _court(texte, taille: int = MAX_TEXTE) -> str:
    t = " ".join(str(texte or "").split())
    return t if len(t) <= taille else t[: taille - 1].rstrip() + "…"


def _element(e) -> str:
    """Un bloc versé dans un document : son type et le début de son texte."""
    if not isinstance(e, dict):
        return f"«{_court(e, 40)}»"
    bloc = str(e.get("bloc") or e.get("type") or "bloc")
    texte = e.get("texte") or e.get("titre") or e.get("legende") or e.get("image")
    if not texte and isinstance(e.get("items"), list) and e["items"]:
        texte = f"{len(e['items'])} puce(s) : {e['items'][0]}"
    if not texte and isinstance(e.get("entetes"), list):
        lignes = e.get("lignes") if isinstance(e.get("lignes"), list) else []
        texte = f"tableau {', '.join(map(str, e['entetes'][:4]))} ({len(lignes)} ligne(s))"
    return f"{bloc} «{_court(texte, 40)}»" if texte else bloc


def _valeur(cle: str, v) -> str:
    if isinstance(v, str):
        return f"«{_court(v)}»"
    if isinstance(v, (int, float, bool)) or v is None:
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, list):
        if cle in ("elements", "blocs", "contenu") or (v and isinstance(v[0], dict)
                                                         and ("bloc" in v[0] or "texte" in v[0])):
            # Un budget, pas un nombre fixe : quatre paragraphes longs
            # débordaient la ligne et le « +N » — le compte de ce qui reste —
            # tombait dans la coupe.
            vus, poids = [], 0
            for e in v[:MAX_ELEMENTS]:
                morceau = _element(e)
                if vus and poids + len(morceau) > BUDGET_ELEMENTS:
                    break
                vus.append(morceau)
                poids += len(morceau)
            reste = len(v) - len(vus)
            return "[" + " ; ".join(vus) + (f" ; +{reste}" if reste > 0 else "") + "]"
        vus = [_court(json.dumps(x, ensure_ascii=False, default=str), 40) for x in v[:3]]
        return "[" + ", ".join(vus) + (f", +{len(v) - 3}" if len(v) > 3 else "") + "]"
    if isinstance(v, dict):
        paires = [f"{k}→{_valeur(k, x)}" for k, x in list(v.items())[:4]]
        return "{" + ", ".join(paires) + (", …" if len(v) > 4 else "") + "}"
    return _court(v)


def _issue(resultat: dict) -> str:
    """ok / ÉCHEC avec sa raison, et les comptes qui disent ce que le geste a donné."""
    brut = str(resultat.get("resultat_masque") or "")
    if not resultat.get("ok"):
        return "ÉCHEC : " + _court(brut.removeprefix("ERREUR :").strip(), 110)
    if brut.startswith("(déjà exécuté"):
        return "rejeu (déjà fait, rien de neuf)"
    try:
        d = json.loads(brut)
    except (ValueError, TypeError):
        return "ok"
    if not isinstance(d, dict):
        return "ok"
    reperes = []
    for cle in ("ajoutes", "ignores", "deja_presents", "total", "remplacements", "nombre",
                "compte", "total_periode", "enregistree", "pret"):
        if cle in d and d[cle] not in (None, "", []):
            reperes.append(f"{cle}={d[cle]}")
    return "ok" + (f" ({', '.join(reperes)})" if reperes else "")


def resume_geste(resultat: dict) -> str:
    """Une ligne : « skill(arg=…, …) → issue »."""
    if not isinstance(resultat, dict):
        return ""
    skill = resultat.get("skill") or "action illisible"
    args = resultat.get("args") if isinstance(resultat.get("args"), dict) else {}
    parts = [f"{k}={_valeur(k, v)}" for k, v in args.items() if k not in _CLES_MUETTES]
    ligne = f"{skill}(" + ", ".join(parts) + ")"
    if len(ligne) > MAX_LIGNE - 40:
        ligne = ligne[: MAX_LIGNE - 41].rstrip() + "…)"
    return f"{ligne} → {_issue(resultat)}"


def journal_des_gestes(resultats: list) -> str:
    """Le journal numéroté du tour, du plus ancien au plus récent.

    Au-delà de MAX_LIGNES_JOURNAL, les plus anciens se replient en un compte par
    skill : même replié, « ajouter_document ×45 » dit ce qu'il faut savoir.
    """
    lignes = [resume_geste(r) for r in (resultats or []) if isinstance(r, dict)]
    lignes = [l for l in lignes if l]
    if not lignes:
        return ""
    entete = ("CE QUE TU AS DÉJÀ FAIT DANS CE TOUR, geste par geste (ta mémoire : "
              "tes blocs d'action des passes précédentes ne sont plus sous tes yeux, "
              "ce journal les remplace). Ne refais pas un geste qui y figure ; si le "
              "même contenu revient plusieurs fois, il est DÉJÀ fait — passe à la suite "
              "ou conclus :\n")
    corps = []
    debut = 0
    if len(lignes) > MAX_LIGNES_JOURNAL:
        debut = len(lignes) - MAX_LIGNES_JOURNAL
        comptes: dict = {}
        for r in resultats[:debut]:
            if isinstance(r, dict):
                comptes[r.get("skill") or "?"] = comptes.get(r.get("skill") or "?", 0) + 1
        corps.append("(gestes 1 à " + str(debut) + " : "
                     + ", ".join(f"{s} ×{n}" for s, n in comptes.items()) + ")")
    for i, l in enumerate(lignes[debut:], start=debut + 1):
        corps.append(f"{i}. {l}")
    return entete + "\n".join(corps) + "\n\n"


def pour_le_modele(resultat: dict) -> dict:
    """L'entrée de résultat telle que le modèle la reçoit : sans les arguments
    bruts (le journal les résume) ni l'empreinte (elle ne lui dit rien)."""
    return {c: v for c, v in (resultat or {}).items() if c not in ("args", "payload_hash")}

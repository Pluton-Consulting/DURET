#!/usr/bin/env python
"""
Test de bout en bout des COMPOSANTS VISUELS et de la MÉMOIRE de conversation.

Appelle le vrai nœud LLM (prompt système réel, vraie cascade de modèles, vraie
anonymisation) et vérifie que :
  1. l'IA émet bien un bloc ```ui quand la demande s'y prête ;
  2. le JSON du bloc est valide et contient les champs REQUIS (sinon le front
     masque le composant, cf. MessageRenderer.tsx) ;
  3. les CHIFFRES fournis se retrouvent intacts dans le composant ;
  4. l'IA se souvient du tour précédent.

Usage (depuis le dossier du docker-compose) :
    docker compose exec -T backend sh -c "PYTHONPATH=. python scripts/test_composants.py"
"""
import asyncio
import json
import re
import sys

sys.path.insert(0, ".")

from agents.agent1 import llm_node  # noqa: E402

# Champs requis par type — miroir de REQUIRED dans frontend/components/chat/MessageRenderer.tsx
REQUIRED = {
    "quote": ["client", "total", "lines"],
    "invoice": ["number", "client", "amount"],
    "table": ["columns", "rows"],
    "bars": ["data"],
    "hbars": ["data"],
    "progress": ["items"],
    "donut": ["segments"],
    "line": ["values"],
    "stat": ["label", "value"],
    "callout": ["text"],
    "quick_replies": ["options"],
    "status_table": ["columns", "rows"],
    "keyvalue": ["rows"],
    "gauge": ["value"],
    "list": ["items"],
    "badge": ["text"],
}

RE_UI = re.compile(r"```ui\s*([\s\S]*?)```")
RE_NUM = re.compile(r"\d+(?:[.,]\d+)?")

VERT, ROUGE, JAUNE, GRIS, RAZ = "\033[92m", "\033[91m", "\033[93m", "\033[90m", "\033[0m"
ok = ko = 0


def verdict(libelle, cond, detail=""):
    global ok, ko
    if cond:
        ok += 1
        print(f"  {VERT}OK{RAZ}   {libelle}")
    else:
        ko += 1
        print(f"  {ROUGE}KO{RAZ}   {libelle}" + (f"\n       {GRIS}{detail}{RAZ}" if detail else ""))


async def tour(question, historique=None):
    """Exécute un vrai tour de chat et retourne (reponse, messages_cumules)."""
    etat = {
        "query": question,
        "anonymized_query": question,
        "anonymized_chunks": [],
        "llm_tier": "standard",
        "thread_id": "test-composants",
        "messages": list(historique or []),
        "entity_map": {},
    }
    res = await llm_node(etat)
    return (res.get("llm_response") or ""), list(historique or []) + list(res.get("messages") or [])


def analyser_blocs(reponse, chiffres_attendus):
    """Valide les blocs ```ui : JSON correct, champs requis, chiffres préservés."""
    blocs = RE_UI.findall(reponse)
    verdict("un composant est émis", bool(blocs),
            "réponse en texte seul :\n       " + reponse[:220].replace("\n", "\n       "))
    if not blocs:
        return
    for brut in blocs:
        try:
            data = json.loads(brut.strip())
        except json.JSONDecodeError as e:
            verdict("JSON du bloc valide", False, f"{e} | {brut[:160]}")
            continue
        verdict("JSON du bloc valide", True)

        t = data.get("type")
        req = REQUIRED.get(t)
        verdict(f"type connu du front : {t}", req is not None, f"type inconnu : {t}")
        if req:
            manquants = [c for c in req
                         if data.get(c) in (None, "", []) or data.get(c) == {}]
            verdict("tous les champs requis présents", not manquants,
                    f"manquants -> {manquants} (le front masquerait le composant)")

        if chiffres_attendus:
            texte = json.dumps(data, ensure_ascii=False)
            perdus = [c for c in chiffres_attendus if c not in texte]
            verdict("les chiffres fournis sont dans le composant", not perdus,
                    f"absents -> {perdus}\n       {texte[:260]}")


async def main():
    print(f"\n{'=' * 62}\n TEST COMPOSANTS + MÉMOIRE\n{'=' * 62}")

    cas = [
        ("Graphique",
         "Montre-moi un graphique du chiffre d'affaires par mois : "
         "Jan 42, Fev 58, Mars 35, Avril 71, Mai 64, Juin 88 (en kEUR).",
         ["42", "58", "35", "71", "64", "88"]),
        ("Devis",
         "Fais un devis pour le client SCI Dupont : 120 m2 de ragreage a 18 EUR/m2 "
         "et 120 m2 de carrelage a 45 EUR/m2.",
         ["120"]),
        ("Tableau",
         "Mets dans un tableau : Ragreage 120 m2 18 EUR, Carrelage 120 m2 45 EUR, "
         "Plinthes 85 ml 12 EUR.",
         ["120", "85"]),
    ]

    historique = None
    for titre, question, chiffres in cas:
        print(f"\n{JAUNE}--- {titre} ---{RAZ}")
        reponse, historique = await tour(question, historique)
        analyser_blocs(reponse, chiffres)

    # La mémoire : question qui n'a de sens QUE si le tour précédent est connu.
    print(f"\n{JAUNE}--- Mémoire de conversation ---{RAZ}")
    reponse, _ = await tour("Et si j'ajoute 20% a chaque ligne, ca donne quoi ?", historique)
    perdu = "je n'ai pas" in reponse.lower() or "quelle ligne" in reponse.lower() \
        or "pouvez-vous préciser" in reponse.lower() or "de quoi parlez" in reponse.lower()
    verdict("l'IA se souvient du tour précédent", not perdu,
            "elle redemande le contexte :\n       " + reponse[:220].replace("\n", "\n       "))

    print(f"\n{'=' * 62}")
    coul = VERT if ko == 0 else ROUGE
    print(f" {coul}RÉSULTAT : {ok} OK / {ko} KO{RAZ}\n{'=' * 62}\n")
    return 1 if ko else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

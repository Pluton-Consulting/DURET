"""
Banc « tout signifie tout » — l'agrégat par client ne se coupe plus à la lettre H.

POURQUOI. Noa, 31/08 : « analyse le CA le plus haut sur tous mes clients » →
« l'affichage a été tronqué après la lettre H, il manque des clients ». La
cause : `_agreger` rendait TOUS les groupes, triés par ordre ALPHABÉTIQUE —
478 clients font ~20 000 caractères de JSON, coupés au plafond de 12 000 au
milieu de l'alphabet. Et « il s'arrête toujours à 10-15-20 mails » : les
détails sont bornés par appel, mais rien ne disait au modèle d'ENCHAÎNER.

CE QUE CE BANC PROUVE, sur le vrai module avec une base doublée (200 clients,
250 devis) : les groupes sont classés du PLUS GRAND au PLUS PETIT, 60 par
page, les TOTAUX portent sur tous, la suite est mécanique (`pour_continuer`),
le résultat sérialisé tient sous le plafond ; par année, l'ordre reste
chronologique ; et le prompt porte la règle TOUT SIGNIFIE TOUT.
"""
import asyncio
import importlib.util
import json
import pathlib
import sys
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend")
sys.path.insert(0, str(BACKEND))
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


# ── La base doublée : 250 devis répartis sur 200 clients, montants croissants ──
DEVIS = []
for i in range(200):
    DEVIS.append({"Client": f"Client-{i:03d}", "Montant HT": f"{(i + 1) * 100},00 €", "Date": f"{2020 + i % 6}-03-01"})
for i in range(50):   # le client 199 cumule 50 devis de plus : c'est LUI le plus haut
    DEVIS.append({"Client": "Client-199", "Montant HT": "1 000,00 €", "Date": "2025-06-15"})


class Conn:
    async def fetch(self, sql, *args):
        if "DISTINCT source_type" in sql:
            return [{"source_type": "devis"}]
        if "SELECT data, champs FROM document_metadata" in sql:
            # `champs` porte le vocabulaire NORMALISÉ (migration 020) — comme la vraie
            # base : c'est par lui que « montant_ht » se lit.
            return [{"data": json.dumps(d, ensure_ascii=False),
                     "champs": json.dumps({"montant_ht": d["Montant HT"], "nom": d["Client"]},
                                          ensure_ascii=False)} for d in DEVIS]
        return []

    async def fetchval(self, sql, *args):
        return len(DEVIS)


class Ctx:
    async def __aenter__(self): return Conn()
    async def __aexit__(self, *a): return False


m = types.ModuleType("database.connection"); m.get_db = lambda: Ctx()
pq = types.ModuleType("database"); pq.connection = m
sys.modules.update({"database": pq, "database.connection": m})
m = types.ModuleType("security.acces"); m.niveaux_visibles = lambda role: {"all"}
pq = types.ModuleType("security"); pq.acces = m
sys.modules.update({"security": pq, "security.acces": m})
m = types.ModuleType("skills.erreurs")
class SkillError(Exception): ...
m.SkillError = SkillError
sys.modules["skills.erreurs"] = m

spec = importlib.util.spec_from_file_location("skills.donnees", BACKEND / "skills" / "donnees.py")
donnees = importlib.util.module_from_spec(spec)
spec.loader.exec_module(donnees)
user = types.SimpleNamespace(id="u1", role="direction")

print(f"\n═══ TOUT SIGNIFIE TOUT — {BACKEND.parent}\n")
r = asyncio.run(donnees.interroger_donnees(
    {"source_type": "devis", "agreger": {"operation": "somme", "colonne": "montant_ht", "par": "client"}}, user))
verifier("200 groupes au total, 60 détaillés (page 1 sur 4)",
         r.get("groupes_total") == 200 and len(r.get("groupes") or []) == 60
         and r.get("page") == 1 and r.get("pages") == 4, str({k: r.get(k) for k in ("groupes_total", "page", "pages")}))
verifier("classés du PLUS GRAND au PLUS PETIT : le client au CA le plus haut est PREMIER",
         (r["groupes"][0]["groupe"] or "").lower() == "client-199" and r["groupes"][0]["resultat"] == 70000.0,
         str(r["groupes"][0]))
verifier("l'ordre est strictement décroissant sur la page",
         all(r["groupes"][i]["resultat"] >= r["groupes"][i + 1]["resultat"] for i in range(len(r["groupes"]) - 1)))
verifier("les TOTAUX portent sur TOUS les groupes, pas sur la page",
         r.get("enregistrements") == 250 and r.get("valeurs_lisibles") == 250)
verifier("la suite est mécanique (pour_continuer → page=2)", "page=2" in (r.get("pour_continuer") or ""))
verifier("la note dit le classement, la page, et que les totaux couvrent tout",
         "plus grand au plus petit" in r["note"] and "page 1" in r["note"] and "TOUS les groupes" in r["note"], r["note"][:200])
verifier("le résultat sérialisé tient sous le plafond généreux (12 000)",
         len(json.dumps(r, ensure_ascii=False, default=str)) < 12000,
         str(len(json.dumps(r, ensure_ascii=False, default=str))))
r4 = asyncio.run(donnees.interroger_donnees(
    {"source_type": "devis", "page": 4,
     "agreger": {"operation": "somme", "colonne": "montant_ht", "par": "client"}}, user))
verifier("page 4 : les 20 derniers groupes, le plus petit en dernier, pas de pour_continuer",
         len(r4["groupes"]) == 20 and r4["groupes"][-1]["resultat"] == 100.0 and not r4.get("pour_continuer"))
verifier("une page au-delà de la dernière retombe sur la dernière",
         asyncio.run(donnees.interroger_donnees(
             {"source_type": "devis", "page": 99,
              "agreger": {"operation": "somme", "colonne": "montant_ht", "par": "client"}}, user)).get("page") == 4)
ra = asyncio.run(donnees.interroger_donnees(
    {"source_type": "devis", "agreger": {"operation": "somme", "colonne": "montant_ht", "par": "annee",
                                         "colonne_date": "date"}}, user))
annees = [g["groupe"] for g in ra["groupes"]]
verifier("par ANNÉE, l'ordre reste chronologique (pas décroissant par valeur)", annees == sorted(annees), str(annees))
rs = asyncio.run(donnees.interroger_donnees(
    {"source_type": "devis", "agreger": {"operation": "somme", "colonne": "montant_ht"}}, user))
verifier("sans `par`, rien ne change : un seul résultat global", rs.get("resultat") == sum((i + 1) * 100 for i in range(200)) + 50000)

agent1 = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
verifier("le prompt porte la règle TOUT SIGNIFIE TOUT (enchaîner les pages ou produire le fichier)",
         "TOUT SIGNIFIE TOUT" in agent1 and "pour_continuer" in agent1 and "échantillon" in agent1)
protocole = (BACKEND / "skills" / "protocol.py").read_text(encoding="utf-8")
verifier("le catalogue dit le classement et la pagination des groupes",
         "plus grand au plus petit" in protocole and "60 par page" in protocole)

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)

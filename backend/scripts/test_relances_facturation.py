"""
Banc « LES RELANCES DE FACTURATION SUIVENT LA CHAÎNE » (08/09 soir).

Demande de Noa : « prépare des skills de facturation ; public : d'abord le
maître d'œuvre, puis l'architecte, puis si le deuxième n'a pas répondu que ça
continue de relancer lui ; le même process même quand c'est planifié ».

CE QUE CE BANC PROUVE (la chaîne et les skills sont EXÉCUTÉS, la base est
doublée) : le destinataire de chaque relance suit la chaîne du régime, une
adresse manquante ne fait relancer personne d'autre, une facture n'est due
qu'échue et hors délai, les cartes portent les faits (référence, montant,
échéance) et le bon destinataire, rien ne part d'ici, l'étape avance quand la
relance est notée, une facture réglée sort sans être supprimée ; la
migration, le catalogue et le raccourci existent. Tombe sur la version d'avant.
"""
import asyncio
import pathlib
import sys
import types
from datetime import date, datetime, timedelta, timezone

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ LES RELANCES DE FACTURATION — {BACKEND.parent}\n")
src = BACKEND / "facturation" / "relances.py"
verifier("le module `facturation/relances.py` existe", src.exists())
if not src.exists():
    sys.exit(1)
sys.modules.setdefault("skills", types.ModuleType("skills"))
lect = types.ModuleType("skills.lecture")


def _lire_date(v):
    try:
        return datetime.fromisoformat(str(v)), "jour"
    except Exception:  # noqa: BLE001
        try:
            j, m, a = str(v).split("/")
            return datetime(int(a), int(m), int(j)), "jour"
        except Exception:  # noqa: BLE001
            return None, None
lect.lire_date = _lire_date
sys.modules["skills.lecture"] = lect
rel = types.ModuleType("facturation.relances")
exec(compile(src.read_text(encoding="utf-8"), str(src), "exec"), rel.__dict__)
sys.modules["facturation"] = types.ModuleType("facturation")
sys.modules["facturation.relances"] = rel

print("— la chaîne")
C = {"client": "compta@client.fr", "maitre_oeuvre": "moe@bet.fr", "architecte": "archi@agence.fr"}
verifier("public : relance 1 → maître d'œuvre, 2 → architecte, 3 et 4 → l'architecte encore",
         [rel.destinataire_de("public", e, C) for e in (1, 2, 3, 4)]
         == [("maitre_oeuvre", "moe@bet.fr"), ("architecte", "archi@agence.fr"),
             ("architecte", "archi@agence.fr"), ("architecte", "archi@agence.fr")])
verifier("privé : le client à chaque relance",
         all(rel.destinataire_de("prive", e, C) == ("client", "compta@client.fr") for e in (1, 2, 5)))
verifier("une adresse manquante ne fait relancer PERSONNE d'autre (rôle rendu, adresse None)",
         rel.destinataire_de("public", 2, {"maitre_oeuvre": "moe@bet.fr"}) == ("architecte", None))
verifier("« marché public », « MOE », « mairie » → public ; le reste → privé",
         all(rel.regime_de(x) == "public" for x in ("public", "Marché public", "MOE", "mairie de Gujan"))
         and rel.regime_de("") == "prive" and rel.regime_de("particulier") == "prive")
verifier("le ton monte : courtoise, ferme, mise en demeure (et y reste)",
         [rel.ton_de(e) for e in (1, 2, 3, 6)] == ["courtoise", "ferme", "mise en demeure", "mise en demeure"])

print("— ce qui est dû")
J = date(2026, 9, 8)
verifier("échue depuis 10 jours, jamais relancée : due",
         rel.relance_due({"echeance": "2026-08-29"}, J)[0] is True)
verifier("pas encore échue : pas due, et la raison dit la date",
         rel.relance_due({"echeance": "2026-09-15"}, J) == (False, "pas encore échue (échéance le 15/09/2026)"))
verifier("relancée il y a 3 jours : pas due avant 7 jours",
         rel.relance_due({"echeance": "2026-08-01", "derniere_relance": datetime(2026, 9, 5, tzinfo=timezone.utc)}, J)[0] is False
         and rel.relance_due({"echeance": "2026-08-01", "derniere_relance": datetime(2026, 8, 30, tzinfo=timezone.utc)}, J)[0] is True)
verifier("réglée ou close : jamais due", rel.relance_due({"echeance": "2026-08-01", "statut": "reglee"}, J)[0] is False)
verifier("échéance illisible : pas due, dit", rel.relance_due({"echeance": "bientôt"}, J) == (False, "échéance illisible"))
dues, ecartees = rel.relances_dues([{"reference": "A", "echeance": "2026-09-01"}, {"reference": "B", "echeance": "2026-08-01"},
                                    {"reference": "C", "echeance": "2026-10-01"}], J)
verifier("les dues d'abord, du plus grand retard au plus petit ; les écartées avec leur raison",
         [f["reference"] for f in dues] == ["B", "A"] and ecartees[0]["reference"] == "C" and "pas encore" in ecartees[0]["raison"])

print("— le texte de la relance")
F = {"reference": "F-2026-041", "client": "Mairie de Gujan", "montant": 12500, "echeance": "2026-08-01", "chantier": "Aire de jeux"}
o1, c1 = rel.corps_de_relance(F, 1, "maitre_oeuvre", "Symbiose Paysage", "Julien")
verifier("relance 1 au maître d'œuvre : les faits (référence, montant, échéance, chantier), le rôle, la signature",
         "F-2026-041" in c1 and "12 500,00 €" in c1 and "01/08/2026" in c1 and "Aire de jeux" in c1
         and "maître d'œuvre" in c1 and c1.rstrip().endswith("Julien") and o1.startswith("Relance 1"))
o3, c3 = rel.corps_de_relance(F, 3, "architecte", "Symbiose Paysage")
verifier("relance 3 à l'architecte : la mise en demeure est annoncée, pas engagée",
         "mise en demeure" in c3 and "Dernière relance" in o3 and "huit jours" in c3)
_, cp = rel.corps_de_relance({**F, "client": "M. Martin"}, 2, "client", "Duret & Sols")
verifier("privé, relance 2 : ferme, échéancier proposé", "sous huit jours" in cp and "échéancier" in cp)

# ── Les skills, contre une base doublée ──
print("— les skills")
LIGNES: dict = {}


class _Conn:
    async def fetchrow(self, sql, *a):
        if "INSERT INTO factures_suivies" in sql:
            uid, ref = a[0], a[1]
            l = LIGNES.get((uid, ref)) or {"id": f"id-{ref}", "user_id": uid, "etape": 0, "statut": "en_cours",
                                          "derniere_relance": None, "created_at": None, "updated_at": None}
            l.update({"reference": ref, "client": a[2], "chantier": a[3], "montant": a[4], "echeance": a[5],
                      "regime": a[6], "contacts": a[7], "notes": a[8]})
            LIGNES[(uid, ref)] = l
            return dict(l)
        if "SET etape = etape + 1" in sql:
            l = LIGNES.get((a[0], a[1]))
            if not l or l["statut"] != "en_cours":
                return None
            l["etape"] += 1; l["derniere_relance"] = a[2]
            return dict(l)
        if "SET statut = $3" in sql:
            l = LIGNES.get((a[0], a[1]))
            if not l:
                return None
            l["statut"] = a[2]
            return dict(l)
        raise AssertionError(sql[:80])

    async def fetch(self, sql, *a):
        uid = a[0]
        if "reference ILIKE" in sql:
            motif = a[1].strip("%").lower()
            return [dict(l) for (u, r), l in LIGNES.items() if u == uid and motif in r.lower()]
        statuts = a[1]
        return [dict(l) for (u, r), l in LIGNES.items() if u == uid and l["statut"] in statuts]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


db = types.ModuleType("database.connection")
db.get_db = lambda: _Conn()
sys.modules["database"] = types.ModuleType("database")
sys.modules["database.connection"] = db
reg = types.ModuleType("skills.registre")


class Declaration:
    def __init__(self, **kw):
        self.__dict__.update(kw)
reg.Declaration = Declaration
sys.modules["skills.registre"] = reg
marque = types.ModuleType("emails.marque")
marque.MARQUE = {"nom": "Symbiose Paysage"}
sys.modules["emails"] = types.ModuleType("emails")
sys.modules["emails.marque"] = marque
sk_src = BACKEND / "skills" / "facturation.py"
verifier("le module `skills/facturation.py` existe", sk_src.exists())
sk = types.ModuleType("skills_facturation_double")
exec(compile(sk_src.read_text(encoding="utf-8"), str(sk_src), "exec"), sk.__dict__)
verifier("cinq gestes déclarés, aucun n'a d'effet externe (l'envoi reste `envoyer_email`), aucun ne supprime",
         set(sk.SKILLS) == {"suivre_facture", "factures_suivies", "relancer_factures", "enregistrer_relance", "facture_reglee"}
         and all(d.effet in ("lecture", "ecriture_interne") for d in sk.SKILLS.values())
         and not any(n.startswith(("supprimer_", "effacer_")) for n in sk.SKILLS))
U = types.SimpleNamespace(id="u1", email="julien@symbiose.fr", name="Julien", role="direction")
r = asyncio.run(sk.suivre_facture({"reference": "F-2026-041", "client": "Mairie de Gujan", "echeance": "01/08/2026",
                                   "montant": "12 500,00 €", "regime": "marché public",
                                   "maitre_oeuvre": "moe@bet.fr", "chantier": "Aire de jeux"}, U))
verifier("suivre : régime public reconnu, montant lu, première relance annoncée au maître d'œuvre, adresse manquante dite",
         r["facture"]["regime"] == "public" and r["facture"]["montant"] == 12500.0
         and "maître d'œuvre" in r["message_final"] and "l'architecte" in r["message_final"]
         and "Demande les adresses manquantes" in r["a_faire"])
try:
    asyncio.run(sk.suivre_facture({"reference": "X", "client": "Y"}, U))
    verifier("sans échéance : refusé", False)
except sk.FactureInvalide as e:
    verifier("sans échéance : refusé avec ce qui manque", "echeance" in str(e))
r = asyncio.run(sk.relancer_factures({}, U))
verifier("relancer : la facture est due, mais sans adresse du maître d'œuvre… si : une carte au MOE, rien à personne d'autre",
         r["nombre"] == 1 and r["cartes"][0]["de"] == "moe@bet.fr" and r["bloc_ui"]["type"] == "reponses_mail"
         and r["bloc_garanti"] is True and "F-2026-041" in r["cartes"][0]["reponse"], r)
verifier("la carte dit l'étape, le ton, le rôle et la raison ; la consigne impose la chaîne et `enregistrer_relance`",
         "relance 1 (courtoise) à le maître d'œuvre" in r["cartes"][0]["synthese"].replace("à le", "à le")
         and "enregistrer_relance" in r["a_faire"] and "IMPOSÉ par la chaîne" in r["a_faire"]
         and "envoyer_email" in r["a_faire"])
r2 = asyncio.run(sk.enregistrer_relance({"reference": "F-2026-041"}, U))
verifier("la relance notée : étape 1, la prochaine ira à l'architecte", r2["facture"]["etape"] == 1 and "l'architecte" in r2["message_final"])
r3 = asyncio.run(sk.relancer_factures({}, U))
verifier("relancée à l'instant : plus rien de dû (délai de 7 jours), et la raison le dit",
         r3["nombre"] == 0 and r3["ecartees"] and "relancée il y a 0 jour" in r3["ecartees"][0]["raison"])
r4 = asyncio.run(sk.relancer_factures({"forcer": True}, U))
verifier("forcée : relance 2 → l'ARCHITECTE, dont l'adresse manque → carte à personne, et c'est DIT",
         r4["nombre"] == 0 and r4["sans_adresse"] == ["F-2026-041 (l'architecte)"] and "adresses manquantes" in r4["a_faire"])
asyncio.run(sk.suivre_facture({"reference": "F-2026-041", "client": "Mairie de Gujan", "echeance": "01/08/2026",
                               "regime": "public", "maitre_oeuvre": "moe@bet.fr", "architecte": "archi@agence.fr"}, U))
r5 = asyncio.run(sk.relancer_factures({"forcer": True}, U))
verifier("l'architecte renseigné : relance 2 à l'architecte, ferme", r5["nombre"] == 1 and r5["cartes"][0]["de"] == "archi@agence.fr"
         and "relance 2 (ferme)" in r5["cartes"][0]["synthese"])
asyncio.run(sk.enregistrer_relance({"reference": "F-2026-041"}, U))
r6 = asyncio.run(sk.relancer_factures({"forcer": True}, U))
verifier("relance 3 : l'architecte ENCORE (la chaîne s'arrête sur lui), mise en demeure annoncée",
         r6["cartes"][0]["de"] == "archi@agence.fr" and "mise en demeure" in r6["cartes"][0]["reponse"])
r7 = asyncio.run(sk.factures_suivies({}, U))
verifier("la liste : tableau garanti avec l'étape et le prochain destinataire",
         r7["bloc_garanti"] and r7["bloc_ui"]["rows"][0][4] == "2" and "l'architecte" in r7["bloc_ui"]["rows"][0][5])
r8 = asyncio.run(sk.facture_reglee({"reference": "F-2026-041"}, U))
verifier("réglée : elle sort des relances SANS être supprimée",
         r8["facture"]["statut"] == "reglee" and ("u1", "F-2026-041") in LIGNES
         and asyncio.run(sk.relancer_factures({"forcer": True}, U))["nombre"] == 0)

print("— le câblage")
mig = BACKEND / "database" / "migrations" / "037_factures_suivies.sql"
verifier("migration 037 : la table, l'unicité (utilisateur, référence), idempotente",
         mig.exists() and "CREATE TABLE IF NOT EXISTS factures_suivies" in mig.read_text(encoding="utf-8")
         and "UNIQUE (user_id, reference)" in mig.read_text(encoding="utf-8"))
ag1 = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
verifier("les cartes de relance ne passent pas par la coupe courte (résultats généreux)",
         '"relancer_factures"' in ag1.split("RESULTATS_GENEREUX = {")[1].split("}")[0])
rac = (BACKEND.parent / "frontend" / "lib" / "raccourcis.ts").read_text(encoding="utf-8")
verifier("le menu éclair propose « Relancer les factures impayées »", "Relancer les factures impayées" in rac)

print(f"\n{'═' * 72}")
if echecs:
    print(f"✗ {len(echecs)} échec(s) : " + ", ".join(echecs)); sys.exit(1)
print("✓ 0 échec")

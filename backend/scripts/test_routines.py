"""
Banc des routines clients / mails — sur le VRAI module.

La base est remplacée par une doublure qui répond aux trois requêtes réelles du
module (jeux de données, comptage, lecture). Les jeux de données imitent ce que
donne un import Excel fait par un client : en-têtes en français, accents,
montants à la française, un fichier « CLIENTS 2025 » qui ne s'appelle pas
« client », et une ligne piège où le nom du client apparaît dans un commentaire
sans être le client de la ligne.
"""
import sys, types, asyncio, json

BACKEND = sys.argv[1] if len(sys.argv) > 1 else "backend"
sys.path.insert(0, BACKEND)

# ══════════════════ Le jeu d'essai ══════════════════
CLIENTS = [
    {"Raison sociale": "SCI Les Tilleuls", "Ville": "Arcachon", "Email": "contact@tilleuls.fr", "Téléphone": "05 56 00 00 01"},
    {"Raison sociale": "Mairie de La Teste", "Ville": "La Teste-de-Buch", "Email": "marches@lateste.fr"},
    {"Raison sociale": "Dupont & Fils", "Ville": "Bordeaux", "Téléphone": "05 56 00 00 03"},
]
DEVIS = [
    {"Référence": "DEV-2025-014", "Client": "SCI Les Tilleuls", "Date": "12/03/2025", "Statut": "signé", "Montant HT": "12 450,50 €"},
    {"Référence": "DEV-2025-041", "Client": "SCI Les Tilleuls", "Date": "02/06/2025", "Statut": "envoyé", "Montant HT": "3 200,00 €"},
    {"Référence": "DEV-2025-009", "Client": "Dupont & Fils", "Date": "18/02/2025", "Statut": "refusé", "Montant HT": "980,00 €"},
]
FACTURES = [
    {"Numéro": "FA-2025-101", "Client": "SCI Les Tilleuls", "Date": "30/04/2025", "Montant TTC": "14 940,60 €"},
    {"Numéro": "FA-2025-118", "Client": "SCI Les Tilleuls", "Date": "15/07/2025", "Montant TTC": "1 200,00 €"},
]
CHANTIERS = [
    # LE PIÈGE : le nom apparaît dans un commentaire, mais le client est un autre.
    {"Chantier": "Résidence du Port", "Client": "Mairie de La Teste",
     "Commentaire": "accès par la parcelle de SCI Les Tilleuls"},
]
BASE = {"CLIENTS 2025": CLIENTS, "devis": DEVIS, "factures": FACTURES, "chantiers": CHANTIERS}


def _normalise(d):
    """Ce que la migration 020 range dans `champs` : le vocabulaire commun.

    Volontairement PARTIEL — un import réel ne sait pas normaliser toutes les
    colonnes. Le banc vérifie ainsi que la fusion des deux sources fonctionne
    même quand `champs` est incomplet.
    """
    correspondance = {"Raison sociale": "nom", "Montant HT": "montant_ht",
                      "Montant TTC": "montant_ttc", "Référence": "reference",
                      "Numéro": "reference", "Client": "nom"}
    return {correspondance[k]: v for k, v in d.items() if k in correspondance}


class FausseConnexion:
    async def fetch(self, sql, *args):
        if "DISTINCT source_type" in sql:
            return [{"source_type": t} for t in sorted(BASE)]
        if "data::text ILIKE" in sql:
            motif = args[1].strip("%").lower()
            out = []
            for type_source, lignes in BASE.items():
                for d in lignes:
                    if motif in json.dumps(d, ensure_ascii=False).lower():
                        out.append({"source_type": type_source, "data": d, "champs": _normalise(d)})
            return out
        if "SELECT data, champs FROM document_metadata" in sql:
            return [{"data": d, "champs": _normalise(d)} for d in BASE.get(args[0], [])]
        return []

    async def fetchval(self, sql, *args):
        if "COUNT(*)" in sql:
            return len(BASE.get(args[0], []))
        return 0


class FauxContexte:
    async def __aenter__(self): return FausseConnexion()
    async def __aexit__(self, *a): return False


# ══════════════════ Doublures de modules ══════════════════
m = types.ModuleType("database.connection"); m.get_db = lambda: FauxContexte()
paquet = types.ModuleType("database"); paquet.connection = m
sys.modules["database"] = paquet; sys.modules["database.connection"] = m

m = types.ModuleType("security.acces"); m.niveaux_visibles = lambda role: {"all", "direction"}
paquet = types.ModuleType("security"); paquet.acces = m
sys.modules["security"] = paquet; sys.modules["security.acces"] = m

m = types.ModuleType("skills.erreurs")
class SkillError(Exception): pass
m.SkillError = SkillError
sys.modules["skills.erreurs"] = m

m = types.ModuleType("skills.registre")
class Declaration:
    def __init__(self, **kw): self.__dict__.update(kw)
m.Declaration = Declaration
sys.modules["skills.registre"] = m

MAILS = {"messages": [
    {"de": "marches@lateste.fr", "objet": "Re: Devis DEV-2025-041", "date": "2026-08-22 09:12",
     "extrait": "Bonjour, pouvez-vous confirmer le délai de pose ?", "non_lu": True},
    {"de": "info@fournisseur.fr", "objet": "Catalogue automne", "date": "2026-08-22 08:40",
     "extrait": "Découvrez nos nouveautés."},
    {"de": "contact@tilleuls.fr", "objet": "RE : visite de chantier", "date": "2026-08-21 17:02",
     "extrait": "Je serai disponible jeudi matin."},
]}
m = types.ModuleType("mail.skills")
async def _lire_mails(data, user): return MAILS
m.lire_mails = _lire_mails
paquet = types.ModuleType("mail"); paquet.skills = m
sys.modules["mail"] = paquet; sys.modules["mail.skills"] = m

import importlib.util, pathlib  # noqa: E402
spec = importlib.util.spec_from_file_location(
    "skills.routines", pathlib.Path(BACKEND) / "skills" / "routines.py")
routines = importlib.util.module_from_spec(spec)
sys.modules["skills.routines"] = routines
spec.loader.exec_module(routines)


class User:
    role = "direction"


echecs = []


def verifier(nom, condition, detail=""):
    print(f"  {'✓' if condition else '✗'} {nom}" + (f"  → {detail}" if detail and not condition else ""))
    if not condition:
        echecs.append(nom)


async def principal():
    print(f"\n═══ ROUTINES CLIENTS & MAILS — {BACKEND}\n")

    # ── 1. Les montants à la française ────────────────────────────────────
    print("1. Lecture des montants (exports comptables réels)")
    for brut, attendu in [("12 450,50 €", 12450.50), ("3 200,00 €", 3200.0),
                          ("1.234,56", 1234.56), ("1,234.56", 1234.56),
                          ("980", 980.0), ("", 0.0), ("n/a", 0.0), ("12 450,50 €", 12450.50)]:
        got = routines._montant(brut)
        verifier(f"« {brut or '(vide)'} » → {attendu}", abs(got - attendu) < 0.01, got)

    # ── 2. Liste des clients ─────────────────────────────────────────────
    print("\n2. Liste des clients")
    r = await routines.liste_clients({}, User())
    verifier("le jeu est trouvé malgré son nom « CLIENTS 2025 »", r.get("trouve"), r.get("message"))
    verifier("le compte est exact", r.get("nombre") == 3, r.get("nombre"))
    verifier("les trois noms sont lus", len(r.get("clients", [])) == 3)
    bloc = r.get("bloc_ui") or {}
    verifier("le bloc est un `table` aux champs du composant",
             bloc.get("type") == "table" and "columns" in bloc and "rows" in bloc, list(bloc))
    verifier("la colonne Téléphone n'apparaît que si elle est renseignée",
             "Téléphone" in bloc.get("columns", []))
    verifier("le nombre exact est imposé au modèle", "3" in (r.get("a_faire") or ""))
    verifier("le web est explicitement exclu",
             "web" in (routines.SKILLS["liste_clients"].description or "").lower())

    # ── 3. Aucun jeu client : ne jamais répondre « zéro » ────────────────
    print("\n3. Jeu de clients absent")
    sauve = dict(BASE)
    BASE.clear(); BASE.update({"devis": DEVIS})
    r = await routines.liste_clients({}, User())
    verifier("le skill dit que le NOM n'existe pas", r.get("trouve") is False)
    verifier("il ne dit pas « aucun client »", "aucun client" not in (r.get("message") or "").lower(),
             r.get("message"))
    verifier("il liste ce qui existe vraiment", "devis" in (r.get("message") or ""))
    BASE.clear(); BASE.update(sauve)

    # ── 4. Fiche client : le recoupement de TOUS les jeux ────────────────
    print("\n4. Fiche client")
    r = await routines.fiche_client({"nom": "SCI Les Tilleuls"}, User())
    verifier("le client est trouvé", r.get("trouve"), r.get("message"))
    jeux = {x["jeu"]: x["enregistrements"] for x in r.get("par_jeu", [])}
    verifier("2 devis comptés", jeux.get("devis") == 2, jeux)
    verifier("2 factures comptées", jeux.get("factures") == 2, jeux)
    verifier("le chantier PIÈGE est écarté (nom cité en commentaire seulement)",
             "chantiers" not in jeux or jeux.get("chantiers") == 0, jeux)
    verifier("le chiffre d'affaires vient de la FACTURATION, pas des devis",
             r.get("source_chiffre_affaires") == "factures", r.get("source_chiffre_affaires"))
    verifier("le chiffre d'affaires est exact (14 940,60 + 1 200,00)",
             r.get("chiffre_affaires") == routines._euros(16140.60), r.get("chiffre_affaires"))
    verifier("les devis sont détaillés avec leur référence",
             any(d["reference"] == "DEV-2025-014" for d in r.get("devis", [])), r.get("devis"))
    verifier("le contact du fichier clients est repris",
             r["identite"].get("Email") == "contact@tilleuls.fr", r.get("identite"))
    bloc = r.get("bloc_ui") or {}
    verifier("le bloc est un `keyvalue` aux champs du composant",
             bloc.get("type") == "keyvalue" and isinstance(bloc.get("rows"), list)
             and all(len(x) == 2 for x in bloc["rows"]), bloc)

    # ── 5. Client inconnu : pas d'invention ──────────────────────────────
    print("\n5. Client inconnu")
    r = await routines.fiche_client({"nom": "Entreprise Fantôme"}, User())
    verifier("le skill dit qu'il ne trouve rien", r.get("trouve") is False)
    verifier("il interdit explicitement d'inventer", "invente" in (r.get("a_faire") or "").lower())
    try:
        await routines.fiche_client({}, User())
        verifier("un appel sans nom est refusé", False, "aucune erreur levée")
    except SkillError:
        verifier("un appel sans nom est refusé", True)

    # ── 6. Point sur les mails ───────────────────────────────────────────
    print("\n6. Check des mails")
    r = await routines.check_mails({}, User())
    verifier("les trois messages sont relevés", r.get("nombre") == 3, r.get("nombre"))
    verifier("les réponses à un fil sont repérées (Re: ET RE :)",
             r.get("reponses_dans_un_fil") == 2, r.get("reponses_dans_un_fil"))
    verifier("le non-lu est compté", r.get("non_lus") == 1, r.get("non_lus"))
    verifier("la consigne interdit d'envoyer quoi que ce soit",
             "n'envoie rien" in (r.get("a_faire") or "").lower())
    verifier("la consigne impose UN SEUL message",
             "un seul message" in (r.get("a_faire") or "").lower())
    MAILS["messages"] = []
    r = await routines.check_mails({}, User())
    verifier("une boîte vide se dit simplement", r.get("nombre") == 0 and "Aucun" in r["message_final"])

    # ── 7. Les déclarations sont exploitables par le registre ────────────
    print("\n7. Déclarations")
    for nom, decl in routines.SKILLS.items():
        verifier(f"« {nom} » : fonction, effet et libellé",
                 callable(decl.fonction) and decl.effet in ("lecture", "ecriture_interne", "externe")
                 and bool(decl.libelle))

    print(f"\n═══ {len(echecs)} échec(s)" + (f" : {', '.join(echecs)}" if echecs else " — tout passe"))
    return 1 if echecs else 0


sys.exit(asyncio.run(principal()))

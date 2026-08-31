"""
Banc de la recherche documentaire à l'échelle — « une énorme recherche aussi
bien qu'une toute petite ».

POURQUOI. Le 31/08, Noa : « il a beaucoup de mal avec les longues requêtes ou
les recherches dans la base s'il y a plusieurs milliers de data ». Ce que le
code faisait : six morceaux, 6 000 caractères, voie vectorielle seule (la
moitié du corpus, sans embedding, était invisible), repli trigramme inopérant
sur des morceaux de 380 mots, extraits pris au DÉBUT du morceau, index ivfflat
construit sur une table vide, résultat coupé à 4 000 caractères, aucune page
suivante ni pour les documents ni pour les enregistrements filtrés.

CE QUE CE BANC PROUVE, sans base ni réseau : les fonctions PURES de
`vectorstore/fusion.py` (fusion par rang réciproque, groupement par document,
fenêtre centrée sur les termes, budget d'extrait) ; le SQL des trois voies et
du compte (`vectorstore/client.py`) ; `rechercher()` et le skill
`rechercher_documents` sur un vectorstore doublé (pages, compte, limite bornée,
budget, filtres) ; la pagination de `interroger_donnees` ; le pool Postgres ;
la migration 027 (HNSW, plein texte français). Sur la version d'avant, il tombe.
"""
import asyncio
import importlib.util
import logging
import pathlib
import re
import sys
import types
from typing import Optional

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend")
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def lire(rel: str) -> str:
    try:
        return (BACKEND / rel).read_text(encoding="utf-8")
    except OSError:
        return ""


print(f"\n═══ RECHERCHE DOCUMENTAIRE À L'ÉCHELLE — {BACKEND.parent}\n")

# ── 1. Le module pur ────────────────────────────────────────────────────────
print("1. Fusion, groupement, fenêtre, budget (vectorstore/fusion.py)")
fusion = None
chemin = BACKEND / "vectorstore" / "fusion.py"
if chemin.exists():
    spec = importlib.util.spec_from_file_location("fusion_banc", chemin)
    fusion = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fusion)
verifier("le module existe", fusion is not None)

if fusion:
    def ch(i, src="doc-A", idx=0, content="", total=3, typ="document_admin", nom=None):
        return {"id": f"c{i}", "source_id": src, "source_type": typ, "chunk_index": idx,
                "chunk_total": total, "content": content or f"morceau {i}",
                "source_filename": nom or f"{src}.pdf"}

    vect = [ch(1), ch(2, "doc-B"), ch(3, "doc-C")]
    lex = [ch(4, "doc-D"), ch(2, "doc-B"), ch(5, "doc-A", 1)]
    f = fusion.fusionner({"vecteur": vect, "texte": lex})
    verifier("union des deux voies, sans doublon", [c["id"] for c in f].count("c2") == 1 and len(f) == 5)
    verifier("le morceau vu par les DEUX voies passe premier", f[0]["id"] == "c2" and f[0]["voies"] == ["vecteur", "texte"])
    verifier("chaque morceau porte ses voies et un score décroissant",
             all("score" in c for c in f) and all(f[i]["score"] >= f[i + 1]["score"] for i in range(len(f) - 1)))
    verifier("une voie vide ne casse rien", [c["id"] for c in fusion.fusionner({"vecteur": [], "texte": lex})] == ["c4", "c2", "c5"])

    g = fusion.grouper_par_document(f)
    verifier("groupé par document, dans l'ordre du meilleur morceau", [d["source_id"] for d in g][:2] == ["doc-B", "doc-A"])
    docA = next(d for d in g if d["source_id"] == "doc-A")
    verifier("le nombre de morceaux correspondants est compté", docA["morceaux_correspondants"] == 2)
    verifier("les extraits sont numérotés à partir de 1 et bornés", docA["extraits"][0]["morceau"] == 1 and len(docA["extraits"]) <= 2)
    beaucoup = fusion.grouper_par_document([ch(i, "doc-Z", i) for i in range(30)])
    verifier("trente morceaux du même document → UN document, 30 morceaux, 2 extraits",
             len(beaucoup) == 1 and beaucoup[0]["morceaux_correspondants"] == 30 and len(beaucoup[0]["extraits"]) == 2)

    verifier("termes : les mots porteurs, longs d'abord, sans accents ni doublons",
             fusion.termes("Les comptes rendus qui parlent de drainage et de Drainage") == ["drainage", "comptes", "parlent", "rendus"])
    court = "Un petit texte."
    verifier("un texte court est rendu tel quel", fusion.fenetre(court, "texte", 200) == court)
    long_ = "Préambule sans intérêt. " * 30 + "Le drainage périphérique de la terrasse a été posé le 3 mai." + " Suite sans intérêt. " * 30
    fen = fusion.fenetre(long_, "drainage terrasse", 160)
    verifier("la fenêtre est CENTRÉE sur le terme cherché", "drainage" in fen and fen.startswith("… ") and fen.endswith(" …"), fen[:80])
    verifier("la fenêtre respecte la longueur", len(fen) <= 160 + 4, str(len(fen)))
    fen2 = fusion.fenetre(long_, "rien de connu", 160)
    verifier("sans terme trouvé : le début du morceau", fen2.startswith("Préambule") and fen2.endswith(" …"))
    verifier("accents : « Périphérique » se trouve avec « peripherique »", "périphérique" in fusion.fenetre(long_, "peripherique", 120))
    verifier("budget : 1 extrait → 1500, 12 → 750, 40 → plancher 250",
             fusion.budget_extrait(1) == 1500 and fusion.budget_extrait(12) == 750 and fusion.budget_extrait(40) == 250)

# ── 2. Le SQL des voies ─────────────────────────────────────────────────────
print("\n2. Les voies de recherche (vectorstore/client.py)")
client = lire("vectorstore/client.py")
lexical = client[client.find("async def search_lexical("): client.find("async def count_lexical(")] if "async def search_lexical(" in client else ""
verifier("voie lexicale : plein texte FRANÇAIS (websearch_to_tsquery)", "websearch_to_tsquery('french', $1)" in lexical)
verifier("voie lexicale : trigrammes de MOTS (<%), pas `content %`", "$1 <% content" in lexical and "content % $1" not in client)
verifier("voie lexicale : les trigrammes complètent le plein texte, sans doublon", "if len(resultats) < top_k" in lexical and "not in vus" in lexical)
verifier("le COMPTE exact des morceaux ET des documents", "COUNT(DISTINCT (source_type, source_id))" in client)
hybride = client[client.find("async def search_hybrid("):] if "async def search_hybrid(" in client else ""
verifier("hybride : la voie lexicale est appelée TOUJOURS, pas seulement sans embedding",
         re.search(r'voies\["texte"\] = await self\.search_lexical', hybride) is not None
         and hybride.find('voies["texte"]') > hybride.find("if query_embedding:"))
verifier("hybride : fusion par rang réciproque", "fusionner(voies)" in hybride)
vecteur = client[client.find("async def search("): client.find("async def search_lexical(")] if "async def search_lexical(" in client else ""
verifier("vecteur : ef_search HNSW aligné sur la profondeur, en SET LOCAL", "SET LOCAL hnsw.ef_search" in vecteur)
verifier("vecteur : garde `embedding IS NOT NULL` et `is_anonymized = true`", "embedding IS NOT NULL" in vecteur and "is_anonymized = true" in vecteur)
verifier("filtres type/fichier en PARAMÈTRE, jamais dans le texte SQL",
         "params.append(list(source_types))" in client and 'params.append(f"%{str(fichier).strip()}%")' in client)

# ── 3. rechercher() sur un vectorstore doublé ───────────────────────────────
print("\n3. rechercher() : profondeur, compte, groupement (vectorstore/rag.py)")
rag = lire("vectorstore/rag.py")
verifier("retrieve() filtre les types DANS la requête (plus de post-filtre qui vide la page)",
         "source_types=list(source_types) if source_types else None" in rag and "allowed = set(source_types)" not in rag)
if fusion and "async def rechercher(" in rag:
    debut = rag.index("PROFONDEUR_MAX")
    fin = rag.index("async def retrieve_as_context(")
    appels = []

    class _VS:
        async def search(self, emb, role, types, top_k, fichier=None):
            appels.append(("vecteur", top_k, types, fichier))
            return [{"id": f"v{i}", "source_id": f"doc-{i % 7}", "source_type": "document_admin",
                     "chunk_index": i, "chunk_total": 9, "content": f"vecteur {i}", "source_filename": f"doc-{i % 7}.pdf"}
                    for i in range(min(top_k, 50))]

        async def search_lexical(self, q, role, types, top_k, fichier=None):
            appels.append(("texte", top_k, types, fichier))
            return [{"id": f"l{i}", "source_id": f"doc-{i % 11}", "source_type": "document_admin",
                     "chunk_index": i, "chunk_total": 9, "content": f"texte {i}", "source_filename": f"doc-{i % 11}.pdf"}
                    for i in range(min(top_k, 80))]

        async def count_lexical(self, q, role, types, fichier=None):
            return 1234, 57

    async def _oui():
        return True

    async def _emb(q):
        return [0.1] * 4

    espace = {"Optional": Optional, "vectorstore": _VS(), "_corpus_has_documents": _oui,
              "embed_query": _emb, "_filtrer_mails": lambda chunks, boites: chunks,
              "logger": logging.getLogger("banc"), "__name__": "banc_rag"}
    sys.path.insert(0, str(BACKEND))
    try:
        exec(rag[debut:fin], espace)  # noqa: S102 — code du dépôt
        rechercher = espace["rechercher"]
        r = asyncio.run(rechercher("drainage terrasse", "direction", limite=6, page=1))
        verifier("les DEUX voies sont interrogées, à la même profondeur", [a[0] for a in appels] == ["vecteur", "texte"] and appels[0][1] == appels[1][1])
        verifier("petite recherche : profondeur plancher 60", appels[0][1] == 60)
        verifier("le compte lexical est repris (57 documents, 1234 morceaux)", r["total_documents"] == 57 and r["total_morceaux"] == 1234)
        verifier("les morceaux sont GROUPÉS par document", 0 < len(r["documents"]) <= 11 and all("morceaux_correspondants" in d for d in r["documents"]))
        appels.clear()
        r = asyncio.run(rechercher("drainage", "direction", limite=20, page=5, source_types=["email"], fichier="CR"))
        verifier("énorme recherche : la profondeur suit la page (20×5×4 = 400, plafond)", appels[0][1] == 400)
        verifier("types et fichier arrivent aux voies", appels[0][2] == ["email"] and appels[0][3] == "CR")
        verifier("un total groupé plus grand que le compte lexical l'emporte", r["total_documents"] >= 57)
        espace["embed_query"] = (lambda q: asyncio.sleep(0, result=None))
        appels.clear()
        r = asyncio.run(rechercher("drainage", "terrain"))
        verifier("sans embedding : la voie lexicale seule, et un résultat quand même", [a[0] for a in appels] == ["texte"] and r["documents"] and r["embedding"] is False)
        r = asyncio.run(rechercher("", "terrain"))
        verifier("requête vide : résultat vide, sans appel", r["documents"] == [] and r["total_documents"] == 0)
    except Exception as e:  # noqa: BLE001
        verifier("rechercher() s'exécute sur le doublé", False, repr(e))
else:
    verifier("rag.py porte rechercher()", False)

# ── 4. Le skill sur le doublé ───────────────────────────────────────────────
print("\n4. Le skill rechercher_documents : limite, page, compte, budget")
src_skill = lire("skills/documents.py")
if fusion and "MAX_LIMITE" in src_skill:
    faux_rag = types.ModuleType("vectorstore.rag")
    etat = {"docs": 0, "appel": None}

    async def _rechercher(query, role, source_types=None, mailboxes=None, limite=6, page=1, fichier=None):
        etat["appel"] = dict(query=query, limite=limite, page=page, fichier=fichier, types=source_types)
        n = etat["docs"]
        return {"documents": [
            {"source": f"CR-{i}.pdf", "type": "document_admin", "source_id": f"cr-{i}",
             "morceaux_correspondants": 3, "morceaux_total": 9, "voies": ["texte"],
             "extraits": [{"morceau": 1, "texte": "Début. " * 80 + "Le drainage a été posé. " + "Suite. " * 120},
                          {"morceau": 4, "texte": "Autre extrait sur le drainage."}]}
            for i in range(n)], "total_documents": max(n, 57), "total_morceaux": 300,
            "embedding": True, "page": page, "limite": limite}

    faux_rag.rechercher = _rechercher
    faux_auth = types.ModuleType("mail.authorization")

    async def _boites(uid):
        return []
    faux_auth.boites_par_id = _boites
    paquet_vs = types.ModuleType("vectorstore"); paquet_vs.__path__ = []
    paquet_mail = types.ModuleType("mail"); paquet_mail.__path__ = []
    sys.modules.update({"vectorstore": paquet_vs, "vectorstore.rag": faux_rag,
                        "vectorstore.fusion": fusion, "mail": paquet_mail, "mail.authorization": faux_auth})

    class _HTTPException(Exception):
        def __init__(self, status_code=0, detail=""):
            super().__init__(detail); self.detail = detail
    espace = {"HTTPException": _HTTPException, "status": types.SimpleNamespace(HTTP_422_UNPROCESSABLE_ENTITY=422),
              "logger": logging.getLogger("banc"), "__name__": "banc_skill"}

    async def _inventaire(role=""):
        return "1 398 devis, 478 clients", True
    espace["_inventaire"] = _inventaire
    try:
        exec(src_skill[src_skill.index("MAX_RESULTATS = 6"): src_skill.index("async def _inventaire(")], espace)  # noqa: S102
        skill = espace["rechercher_documents"]
        user = types.SimpleNamespace(id="u1", role="direction")
        etat["docs"] = 57
        r = asyncio.run(skill({"requete": "drainage terrasse"}, user))
        verifier("par défaut : 6 documents, page 1 sur 10, compte exact",
                 r["nombre"] == 6 and r["page"] == 1 and r["pages"] == 10 and r["total_documents"] == 57, str({k: r.get(k) for k in ("nombre", "page", "pages", "total_documents")}))
        verifier("le compte se dit en mots, et la suite est mécanique",
                 r["compte"].startswith("57 document(s) correspondent") and "page=2" in (r["pour_continuer"] or ""))
        verifier("chaque document dit ses morceaux correspondants et ses extraits", r["resultats"][0]["morceaux_correspondants"] == 3 and len(r["resultats"][0]["extraits"]) == 2)
        verifier("l'extrait est une FENÊTRE centrée sur le terme, pas le début", "drainage" in r["resultats"][0]["extrait"] and r["resultats"][0]["extrait"].startswith("… "))
        verifier("`extrait` (le meilleur) reste pour les lecteurs d'avant", r["resultats"][0]["extrait"] == r["resultats"][0]["extraits"][0]["texte"])
        r = asyncio.run(skill({"requete": "drainage", "limite": 99, "page": "3", "fichier": "CR", "types": "document_admin,email"}, user))
        verifier("limite bornée à 20, page lue, fichier et types transmis",
                 etat["appel"]["limite"] == 20 and etat["appel"]["page"] == 3 and etat["appel"]["fichier"] == "CR" and etat["appel"]["types"] == ["document_admin", "email"])
        verifier("page 3 de 20 : les documents 41 à 57", r["nombre"] == 17 and r["resultats"][0]["source"] == "CR-40.pdf" and r["pour_continuer"] is None)
        taille = sum(len(e["texte"]) for d in r["resultats"] for e in d["extraits"])
        verifier("une page de 17 documents tient dans le budget (extraits raccourcis)", taille <= 9000 + 17 * 2 * 8, str(taille))
        r = asyncio.run(skill({"requete": "drainage", "page": 50}, user))
        verifier("une page au-delà de la dernière le dit, sans inventer", r["nombre"] == 0 and "page(s)" in r["message"] and "page 10" in r["a_faire"])
        etat["docs"] = 0
        r = asyncio.run(skill({"requete": "licorne"}, user))
        verifier("rien trouvé : l'inventaire côté humain, la consigne côté modèle", r["nombre"] == 0 and "1 398 devis" in r["message"] and "connaissances_acquises" in r["a_faire"])
        try:
            asyncio.run(skill({}, user))
            verifier("sans requête : refus", False)
        except _HTTPException:
            verifier("sans requête : refus", True)
    except Exception as e:  # noqa: BLE001
        verifier("le skill s'exécute sur le doublé", False, repr(e))
else:
    verifier("skills/documents.py porte limite/page/fichier (MAX_LIMITE)", False)

# ── 5. Le câblage ───────────────────────────────────────────────────────────
print("\n5. Le câblage : catalogue, plafonds, données, pool, migration")
protocole = lire("skills/protocol.py")
verifier("catalogue : rechercher_documents accepte types, limite, page, fichier",
         re.search(r'"rechercher_documents": \(.*?\["requete"\], \["types", "limite", "page", "fichier"\]', protocole, re.S) is not None)
verifier("catalogue : interroger_donnees accepte page",
         re.search(r'"interroger_donnees": \(.*?"depuis", "page"\]', protocole, re.S) is not None)
agent1 = lire("agents/agent1.py")
m = re.search(r"RESULTATS_GENEREUX = \{([^}]*)\}", agent1)
genereux = set(re.findall(r'"(\w+)"', m.group(1))) if m else set()
verifier("résultats généreux : rechercher_documents et interroger_donnees", {"rechercher_documents", "interroger_donnees"} <= genereux, str(sorted(genereux)))
donnees = lire("skills/donnees.py")
verifier("interroger_donnees : une PAGE d'enregistrements (OFFSET) et la suite mécanique",
         "page: int = 1" in donnees and "OFFSET $" in donnees and '"pour_continuer"' in donnees and 'data.get("page")' in donnees)
verifier("la note dit la page (« page 2 sur 80 »)", "page {page} sur {pages}" in donnees)
connexion = lire("database/connection.py")
verifier("pool : 16 connexions et un délai de commande (plus d'attente infinie)", "max_size=16" in connexion and "command_timeout=180" in connexion)
migration = lire("database/migrations/027_recherche_documents.sql")
verifier("migration 027 : HNSW remplace l'ivfflat construit à vide",
         "DROP INDEX IF EXISTS idx_documents_embedding_cosine" in migration and "USING hnsw (embedding vector_cosine_ops)" in migration)
verifier("migration 027 : index plein texte français", "USING gin (to_tsvector('french', content))" in migration)
verifier("migration 027 : idempotente (IF NOT EXISTS partout)", migration.count("CREATE INDEX IF NOT EXISTS") == 3 and "CREATE INDEX idx" not in migration)

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)

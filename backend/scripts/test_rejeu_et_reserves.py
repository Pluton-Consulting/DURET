"""
Banc (17/09) : un travail BLOQUÉ par une faute de programme repart après une nouvelle livraison, et les
réserves d'un quantitatif se regroupent. Relevé : le quantitatif réel de La Teste est resté « bloqué »
sur un AttributeError d'une ancienne version (rejoué à blanc avec le code du jour, il va au bout), et
il portait 102 réserves pour 52 lignes, toutes au rez-de-chaussée. SQLite en mémoire, sans réseau.

    python backend/scripts/test_rejeu_et_reserves.py backend
"""
import json, os, sqlite3, sys
from pathlib import Path

BACKEND = Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
sys.path.insert(0, str(BACKEND))
for k, v in {"DATABASE_URL": "postgresql://x:x@localhost/x", "JWT_SECRET_KEY": "x" * 40, "RESEND_API_KEY": "x"}.items():
    os.environ.setdefault(k, v)
ECHECS = []


def verifier(nom, condition, detail=""):
    print(("  ✓ " if condition else "  ✗ ") + nom + (f"  → {detail}" if detail and not condition else ""))
    if not condition:
        ECHECS.append(nom)


from ressources import documents_file as df

c = sqlite3.connect(":memory:"); c.row_factory = sqlite3.Row
c.execute("CREATE TABLE file_documentaire (id TEXT, statut TEXT, essais INT, annonce INT, prochain REAL, resultat TEXT)")
lignes = {
    "ancien": {"note": "Une étape a échoué (AttributeError). Les étapes acquises sont conservées."},          # bloqué AVANT ce correctif
    "neuf": {"note": "Une étape a échoué (TypeError).", "faute_programme": "TypeError", "version": "aaa111"},
    "meme": {"note": "Une étape a échoué (KeyError).", "faute_programme": "KeyError", "version": "bbb222"},
    "metier": {"note": "Aucune quantité avec affectation suffisamment prouvée.", "definitif": True},
    "reseau": {"note": "Une étape a échoué (TimeoutError). Les étapes acquises sont conservées."},
    "epuise": {"note": "Une étape a échoué (NameError).", "faute_programme": "NameError", "version": "x", "rejoue_pour": ["y", "z"]},
}
for k, r in lignes.items():
    c.execute("INSERT INTO file_documentaire VALUES (?,?,?,?,?,?)", (k, "bloque", 5, 1, 0, json.dumps(r)))
print("1. Remise en file après livraison")
remis = df.rejouer_apres_livraison(c, "bbb222")
verifier("une faute de programme d'une AUTRE version repart (y compris un blocage d'avant ce correctif)", sorted(remis) == ["ancien", "neuf"], str(remis))
r = dict(c.execute("SELECT * FROM file_documentaire WHERE id='ancien'").fetchone())
verifier("le travail repart de zéro essai, et son résultat sera ANNONCÉ dans la conversation", r["statut"] == "attente" and r["essais"] == 0 and r["annonce"] == 0)
etats = {x["id"]: x["statut"] for x in c.execute("SELECT id,statut FROM file_documentaire")}
verifier("même version, échec métier, panne de réseau : rien ne repart", etats["meme"] == etats["metier"] == etats["reseau"] == "bloque")
verifier("deux rejeux au plus par travail", etats["epuise"] == "bloque")
c.execute("UPDATE file_documentaire SET statut='bloque' WHERE id='ancien'")
verifier("une seule fois par version : la même livraison ne relance pas en boucle", df.rejouer_apres_livraison(c, "bbb222") == [])
verifier("version inconnue (poste de dev) : rien ne bouge", df.rejouer_apres_livraison(c, "") == [])
src = (BACKEND / "ressources" / "documents_file.py").read_text(encoding="utf-8")
verifier("la trace de la faute part au journal, et le résultat dit OÙ (fichier:ligne), jamais une donnée", "exc_info=True" in src and "'ou':_ou(e)" in src)
verifier("le compteur de rejeux survit à l'essai suivant", "resultat['rejoue_pour']=precedent['rejoue_pour']" in src)

print("2. Les réserves d'un quantitatif")
from skills.quantitatifs import regrouper_reserves, couverture_des_niveaux, MAX_RESERVES_RESUMEES
brut = (["Aucune hauteur sous plafond ni périmètre n'est disponible ; aucune quantité de faïence murale ne peut être calculée."] * 30
        + ["Aucune hauteur sous plafond n'est disponible : la faïence murale ne peut pas être calculée."] * 20
        + ["Les quantités de plinthes en ml ne sont pas déterminables : aucun périmètre de plinthe n'est justifié par local."] * 40
        + ["La répartition des chapes entre les lots 11 et 13 reste à confirmer."])
resume, detail = regrouper_reserves(brut)
verifier("91 remarques → 3 idées, la plus fréquente en tête, avec son compte", len(resume) == 3 and "faïence" in resume[0] and "50 fois" in resume[0] and "plinthes" in resume[1] and "40 fois" in resume[1], str(resume))
verifier("la remarque unique n'est pas noyée", any("chapes" in x for x in resume))
verifier("rien n'est perdu : le détail garde chaque formulation", len(detail) == 4)
beaucoup = ["Point %s sur le local %s à vérifier" % (chr(65 + i), i * 37) for i in range(40)]
import hashlib
mot = lambda i, j: "".join(chr(97 + int(x, 16) % 26) for x in hashlib.md5(f"{i}-{j}".encode()).hexdigest()[:9])
resume, detail = regrouper_reserves([" ".join(mot(i, j) for j in range(4)) for i in range(40)])
verifier("au-delà du plafond, le résumé renvoie à la feuille de détail", len(resume) == MAX_RESERVES_RESUMEES + 1 and "Réserves (détail)" in resume[-1] and len(detail) == 40)
t = couverture_des_niveaux([{"niveau": "RDC"}] * 52, ["05 PLAN RDC.pdf", "06 PLAN R+1.pdf", "07 PLAN R+2.pdf", "CCTP lot 11.pdf"])
verifier("un métré du seul rez-de-chaussée le DIT en tête quand les plans R+1 et R+2 sont fournis", t.startswith("COUVERTURE INCOMPLÈTE") and "R+1, R+2" in t, t)
verifier("tous les niveaux couverts : aucune alerte", couverture_des_niveaux([{"niveau": "RDC"}, {"niveau": "R+1"}, {"niveau": "R + 2"}], ["PLAN RDC.pdf", "PLAN R+1.pdf", "PLAN R+2.pdf"]) == "")
verifier("aucun niveau dans les noms de pièces : aucune alerte inventée", couverture_des_niveaux([{"niveau": "RDC"}], ["CCTP.pdf", "DPGF.xlsx"]) == "")

print(("✗ %d échec(s) : %s" % (len(ECHECS), ", ".join(ECHECS))) if ECHECS else "✓ 0 échec")
sys.exit(1 if ECHECS else 0)

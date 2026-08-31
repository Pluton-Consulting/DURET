"""
Banc de la carte « Ce que l'entreprise a confié à l'outil » — les chiffres.

POURQUOI. Noa, 31/08 : « les chiffres ne sont pas les bons ». Deux défauts dans
le SQL du tableau de bord :
  * « documents » comptait les MORCEAUX d'ingestion (COUNT(*) sur la table des
    chunks, ~15 par document) : des milliers affichés pour quelques centaines
    de fichiers réels ;
  * clients / fournisseurs / devis cherchaient des noms de jeux DEVINÉS
    (source_type = 'client') alors qu'un import garde le nom de son fichier
    (« CLIENTS 2025 ») — selon le nom réel, la carte montrait zéro.
Ce banc lit la requête livrée : documents DISTINCTS, rapprochement par racine.
"""
import pathlib
import re
import sys

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend")
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ CARTE MÉMOIRE DU TABLEAU DE BORD — {BACKEND.parent}\n")
src = (BACKEND / "routers" / "tableau.py").read_text(encoding="utf-8")
bloc = src[src.index("Mémoire d'entreprise") : src.index("synchros = ")]
verifier("« documents » compte les documents DISTINCTS, pas les morceaux d'ingestion",
         "COUNT(DISTINCT (source_type, source_id)) FROM documents" in bloc
         and "(SELECT COUNT(*) FROM documents)" not in bloc)
verifier("« devis » se rapproche par racine (un jeu « DEVIS 2025 » compte)",
         re.search(r"lower\(source_type\) LIKE '%devis%'", bloc) is not None)
verifier("« clients » se rapproche par racine (« CLIENTS 2025 », « customer »…)",
         "%client%" in bloc and "%customer%" in bloc and "IN ('client','clients')" not in bloc)
verifier("« fournisseurs » se rapproche par racine (supplier, vendor)",
         "%fournisseur%" in bloc and "%supplier%" in bloc)

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)

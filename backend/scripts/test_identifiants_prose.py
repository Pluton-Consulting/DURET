"""
Banc du rédacteur — « aucun identifiant technique dans la prose ».

POURQUOI. Le 31/08, Noa relit un tour de retouche RÉUSSI et lit dans la réponse :
« Les résultats indiquent les clés ["e527f1b03524955df936f7ff"], la source
"bc4191bbe1154b53f191d130" » — puis, sur un Word produit : « avec l'identifiant
xz-U9coZQtoswQYDsniBnM9pr1BfwJMA ». Le rédacteur de secours (`_rediger_par_le_modele`)
recevait le résultat BRUT du skill, clés de dépôt et drapeaux internes compris,
et le modèle les recopiait. Son verdict : « rien à dire à part qu'il ne doit pas
mentionner les id incompréhensibles ».

CE QUE CE BANC PROUVE, sans LangGraph ni base : `_sans_identifiants` (extraite du
source livré et exécutée telle quelle) retire les clés techniques d'un JSON et
toute valeur qui a la forme d'un identifiant, dans du JSON comme dans du texte —
et LAISSE ce qui est de l'information : un numéro de devis, un montant, un nom
de fichier, une balise d'anonymisation, un compte. Puis que le rédacteur passe
bien par elle et que sa consigne interdit la tuyauterie.
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


src = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")

# La fonction et ses deux constantes, extraites du source et exécutées telles
# quelles : on teste le code livré, pas une copie.
debut = src.index("_CLES_TECHNIQUES = frozenset({")
fin = src.index("async def _rediger_par_le_modele(")
espace: dict = {}
exec(src[debut:fin], espace)  # noqa: S102 — code du dépôt, pas une entrée externe
_sans_identifiants = espace["_sans_identifiants"]

print(f"\n═══ IDENTIFIANTS DANS LA PROSE — {BACKEND.parent}\n")

print("1. Les deux cas relevés en production disparaissent")
retouche = ('{"ok": true, "genere": true, "essai": false, "cles": ["e527f1b03524955df936f7ff"], '
            '"source": "bc4191bbe1154b53f191d130", "message_final": "Voici l\'avant / après."}')
s = _sans_identifiants(retouche)
verifier("clé de dépôt retirée (liste `cles`)", "e527f1b03524955df936f7ff" not in s)
verifier("clé source retirée (valeur en forme d'identifiant)", "bc4191bbe1154b53f191d130" not in s)
verifier("le message_final, lui, reste", "Voici l'avant / après." in s)

word = ('{"ok": true, "document_id": "xz-U9coZQtoswQYDsniBnM9pr1BfwJMA", "titre": "Informations sur Symbiose Paysage", '
        '"format": "docx", "octets": 39109, "elements": 68, "pages_estimees": 4}')
s = _sans_identifiants(word)
verifier("document_id retiré", "xz-U9coZQtoswQYDsniBnM9pr1BfwJMA" not in s)
verifier("titre, format et compte de pages conservés",
         "Informations sur Symbiose Paysage" in s and '"docx"' in s and "68" in s)

print("\n2. Ce qui est de l'information n'est pas touché")
info = ('{"client": "ATHENA Piscine & Spa", "devis": "DV0001410", "montant": "12 450,00 €", '
        '"fichier": "clients.xlsx", "email": "[PER_3]", "total": 478, "siret": "[À COMPLÉTER]", '
        '"date": "2026-08-31T10:06:29"}')
s = _sans_identifiants(info)
for attendu in ("ATHENA Piscine & Spa", "DV0001410", "12 450,00 €", "clients.xlsx", "[PER_3]", "478",
                "[À COMPLÉTER]", "2026-08-31T10:06:29"):
    verifier(f"conservé : {attendu}", attendu in s)

print("\n3. Le texte libre est traité aussi, et un JSON cassé ne fait pas planter")
texte = "Image déposée sous la clé e527f1b03524955df936f7ff, dérivée de bc4191bbe1154b53f191d130. Devis DV0001410 joint."
s = _sans_identifiants(texte)
verifier("identifiants retirés du texte libre", "e527f1b" not in s and "bc4191bb" not in s)
verifier("le numéro de devis survit dans le texte libre", "DV0001410" in s)
verifier("un JSON tronqué est traité comme du texte, sans exception",
         "e527f1b" not in _sans_identifiants('{"cles": ["e527f1b03524955df936f7ff"], "x": '))
verifier("vide → vide", _sans_identifiants("") == "" and _sans_identifiants(None) == "")

print("\n4. Le rédacteur passe par le filtre, et sa consigne le dit")
corps = src[src.index("async def _rediger_par_le_modele("):]
corps = corps[:corps.index("\ndef _tracer_filet")]
verifier("le résultat masqué traverse _sans_identifiants avant le modèle",
         '_sans_identifiants(str(r.get("resultat_masque") or ""))' in corps)
verifier("la consigne interdit les identifiants et les drapeaux internes",
         "Ne cite JAMAIS d'identifiant" in corps and "drapeau interne" in corps)

print(f"\n═══ {len(echecs)} échec(s)" + (f" : {', '.join(echecs)}" if echecs else " — tout passe"))
sys.exit(1 if echecs else 0)

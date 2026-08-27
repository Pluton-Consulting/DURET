"""
Banc des MESSAGES LISIBLES — un skill parle à deux publics, pas avec un seul mot.

Relevé en direct le 27/08, question 5 du cahier de démo. À l'écran, dans le
chat, l'utilisateur a lu ceci :

  « Aucun enregistrement ne correspond EXACTEMENT à ces valeurs. Les filtres
    sont sensibles à l'orthographe : rappelle interroger_donnees avec le seul
    source_type pour voir les valeurs réellement présentes. »

C'est une consigne écrite POUR LE MODÈLE — tutoiement, nom de skill, nom de
paramètre — et elle arrive telle quelle sous les yeux d'un dirigeant. La cause
n'est pas une faute de rédaction mais un champ qui sert deux publics : le
`message` d'un skill est relu par le modèle ET affiché à l'utilisateur quand le
modèle ne rédige pas (`_message_apres_action`, rendu de secours).

La convention du projet existe déjà : `message` pour la personne, `a_faire` /
`a_savoir` pour le modèle. Ce banc vérifie qu'on ne les confond plus.

Ni base, ni réseau : on lit le source et on juge les chaînes littérales.

  python3 scripts/test_messages_humains.py backend
"""
import sys, ast, pathlib

BACKEND = sys.argv[1] if len(sys.argv) > 1 else "backend"
racine = pathlib.Path(BACKEND)

VERT, ROUGE, GRIS, RAZ = "\x1b[92m", "\x1b[91m", "\x1b[90m", "\x1b[0m"
echecs = 0


def controle(titre, ok, detail=""):
    global echecs
    if ok:
        print(f"  {VERT}✓{RAZ} {titre}")
    else:
        echecs += 1
        print(f"  {ROUGE}✗{RAZ} {titre}" + (f"{GRIS}\n      {detail}{RAZ}" if detail else ""))


def textes_de(noeud):
    """Toutes les parties littérales d'une valeur : f-string, concaténation, constante."""
    out = []
    for n in ast.walk(noeud):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            out.append(n.value)
    return " ".join(out)


def messages_du_fichier(chemin):
    """Chaque valeur associée à une clé `message` dans un dict littéral."""
    arbre = ast.parse(chemin.read_text(encoding="utf-8"))
    trouves = []
    for n in ast.walk(arbre):
        if not isinstance(n, ast.Dict):
            continue
        for cle, val in zip(n.keys, n.values):
            if isinstance(cle, ast.Constant) and cle.value in ("message", "message_final"):
                trouves.append((getattr(n, "lineno", 0), textes_de(val)))
    return trouves


# Ce qui trahit une phrase écrite pour le modèle et non pour la personne.
TUYAUTERIE = ["`", "source_type", "interroger_donnees", "agreger.", "payload_hash",
              "bloc ui", "```"]
IMPERATIFS = ["reformule", "rappelle ", "ne conclus pas", "passe plutôt", "vérifie `",
              "insère un bloc", "n'écris pas", "affiche la liste"]

FICHIERS = ["skills/donnees.py", "skills/routines.py"]

print("\n\x1b[1mCE QUE LA PERSONNE LIT NE DOIT PAS ÊTRE UNE CONSIGNE AU MODÈLE\x1b[0m\n")

total = 0
for rel in FICHIERS:
    chemin = racine / rel
    if not chemin.exists():
        print(f"  {GRIS}· {rel} absent de ce projet{RAZ}")
        continue
    msgs = messages_du_fichier(chemin)
    total += len(msgs)
    fautifs = []
    for ligne, texte in msgs:
        bas = texte.lower()
        motifs = [m for m in TUYAUTERIE if m in texte] + [m for m in IMPERATIFS if m in bas]
        if motifs:
            fautifs.append(f"{rel}:{ligne} → {', '.join(sorted(set(motifs)))}"
                           f"\n        « {texte[:110]}… »")
    controle(f"{rel} : les {len(msgs)} messages sont écrits pour un humain",
             not fautifs, "\n      ".join(fautifs))

controle("des messages ont bien été trouvés (le banc mord vraiment)", total >= 4,
         f"{total} message(s) analysé(s) — un extracteur muet passerait pour vert")

# La consigne au modèle doit exister quelque part : on ne l'a pas perdue en route.
src = (racine / "skills" / "donnees.py").read_text(encoding="utf-8")
controle("la consigne technique survit dans `a_faire`",
         src.count('"a_faire"') >= 4,
         f'{src.count(chr(34) + "a_faire" + chr(34))} occurrence(s) — '
         "le modèle a besoin de savoir comment se rattraper")
controle("`a_faire` n'est jamais ce qui s'affiche",
         '"message_final"' not in src or "a_faire" not in src.split('"message_final"')[0][-200:])

print()
if echecs:
    print(f"{ROUGE}{echecs} contrôle(s) en échec.{RAZ}")
    sys.exit(1)
print(f"{VERT}Tous les contrôles passent.{RAZ}")

"""
Banc « LE BUT ATTEINT FERME LE TOUR » — export Langfuse de Duret du 08/09, 11:09 et 11:14.

1. « ouvre un appel d'offre au hasard » : le règlement de consultation est
   OUVERT au deuxième geste (11:10:16), puis le modèle repart lister neuf
   autres dossiers pendant deux minutes, rouvre le même fichier, et la boucle
   ne se ferme que sur un rejeu à l'identique. 173 s pour un tour qui en
   valait 30. Rien ne disait à la mécanique que le but était atteint.
2. « ouvre le dce de ikos village » : `nas_ouvrir` sur un chemin dont le
   modèle avait ENCODÉ les accents (`r%C3%A9emploi-%C3%A0`) — le serveur ne
   connaît pas ce fichier-là.

CE QUE CE BANC PROUVE : le prédicat `demande_d_ouvrir_un_seul` reconnaît les
demandes exactes de prod et laisse passer le pluriel ; `tools_node` ferme le
tour après une lecture réussie quand la demande visait UN document (contrôle
sur le source, la mécanique `_sortir` est celle des autres gardes) ; un chemin
encodé se décode avant de toucher le serveur (exécuté). Tombe sur l'avant.
"""
import pathlib
import re
import sys
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ LE BUT ATTEINT FERME LE TOUR — {BACKEND.parent}\n")

sys.modules["agents"] = types.ModuleType("agents")
chemin = BACKEND / "agents" / "annonce.py"
ann = types.ModuleType("agents.annonce")
ann.__dict__["__file__"] = str(chemin)
exec(compile(chemin.read_text(encoding="utf-8"), str(chemin), "exec"), ann.__dict__)

verifier("`demande_d_ouvrir_un_seul` existe", callable(getattr(ann, "demande_d_ouvrir_un_seul", None)))
if callable(getattr(ann, "demande_d_ouvrir_un_seul", None)):
    p = ann.demande_d_ouvrir_un_seul
    verifier("« ouvre un appel d'offre au hasard » (11:09) vise UN document", p("ouvre un appel d'offre au hasard"))
    verifier("« ouvre le dce de ikos village » (11:14) aussi", p("ouvre le dce de ikos village"))
    verifier("« ouvre le pdf le plus lourd de ce dossier » (04:44) aussi", p("ouvre le pdf le plus lourd de ce dossier"))
    verifier("« affiche moi le document », « montre-moi le règlement » aussi",
             p("affiche moi le document") and p("montre-moi le règlement de consultation"))
    verifier("« ouvre moi tout les pdf d'un dossier » (10:44) est un PLURIEL : on continue",
             not p("ouvre moi tout les pdf d'un dossier d'appel d'offres"))
    verifier("« affiche les différents pdf », « lis chaque CCTP », « ouvre les 3 plans » : pluriel",
             not p("affiche les différent pdf dans le 2029 airborne") and not p("lis chaque CCTP")
             and not p("ouvre les 3 plans"))
    verifier("« liste les dossiers du drive », « il y a quoi dans ETUDES EN COURS » : pas une ouverture",
             not p("liste moi les dossier du drive") and not p("il y a quoi comme document dans 03-Appel d'offres etudes"))

agent1 = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
_lecture = re.search(r"SKILLS_LECTURE_FICHIER = frozenset\(\{([^}]*)\}\)", agent1, re.S)
verifier("agent1 connaît les gestes qui LISENT un fichier (nas et drive, ouvrir et lire, pièce jointe)",
         _lecture and all(f'"{g}"' in _lecture.group(1) for g in
                          ("nas_ouvrir", "nas_lire", "drive_ouvrir", "drive_lire", "lire_piece_jointe")))
noeud = agent1[agent1.find("async def tools_node"):agent1.find("_CLES_TECHNIQUES = ")]
verifier("tools_node ferme le tour (`_sortir`) après une lecture RÉUSSIE avec contenu, si la demande visait UN document",
         'action["skill"] in SKILLS_LECTURE_FICHIER' in noeud
         and 'demande_d_ouvrir_un_seul(state.get("query") or "")' in noeud
         and noeud.find("But atteint") > noeud.find('exp = expert_du_skill(action["skill"])'))
verifier("…en gardant l'attribution d'expert et la carte du fil (`{**maj, **_sortir(…)}`)",
         "return {**maj, **_sortir(" in noeud)
verifier("…et la note dit de ne rien ouvrir ni lister de plus",
         "N'en ouvre pas d'autre, ne liste rien de plus" in noeud)
verifier("`sortie` est posée avant le `try` (un `if` ne lit jamais une locale non affectée)",
         noeud.find("    sortie = None\n") > 0 and noeud.find("    sortie = None\n") < noeud.find("brut = await execute_skill("))

# ── Le chemin encodé ──
if (BACKEND / "nas" / "acces.py").exists():
    src = (BACKEND / "nas" / "acces.py").read_text(encoding="utf-8")
    esp = {"posixpath": __import__("posixpath")}
    debut = src.find("def decoder(chemin")
    fin = src.find("\ndef verifier_role")
    verifier("`decoder` existe dans nas/acces.py", debut > 0)
    if debut > 0:
        exec(compile(src[debut:fin], "acces_extrait", "exec"), esp)
        encode = "/home/Drive/ETUDES EN COURS/AOS - ikos-village-du-r%C3%A9emploi-%C3%A0-bordeaux - DCE.zip"
        verifier("le chemin ENCODÉ de 11:15 redevient « réemploi-à » avant de toucher le serveur",
                 esp["normaliser"](encode) == "/home/Drive/ETUDES EN COURS/AOS - ikos-village-du-réemploi-à-bordeaux - DCE.zip",
                 esp["normaliser"](encode))
        verifier("un « % » isolé dans un vrai nom reste tel quel (« 100% coton.pdf »)",
                 esp["normaliser"]("/home/Drive/100% coton.pdf") == "/home/Drive/100% coton.pdf")
    verifier("la recherche par nom et `ouvrir` décodent aussi",
             "motif = decoder((motif or \"\").strip())" in src
             and "demande = decoder((nom_ou_chemin or \"\").strip())" in (BACKEND / "outils" / "nas.py").read_text(encoding="utf-8"))
else:
    sk = (BACKEND / "skills" / "outils.py").read_text(encoding="utf-8")
    verifier("`drive_ouvrir` décode un nom encodé à la façon d'une URL", "unquote(nom)" in sk)

print(f"\n{'═' * 72}")
if echecs:
    print(f"✗ {len(echecs)} échec(s) : " + ", ".join(echecs))
    sys.exit(1)
print("✓ 0 échec")

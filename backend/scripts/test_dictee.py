"""
Banc de la DICTÉE — parler plutôt que taper, dans la barre de saisie.

LA DEMANDE (03/09, Noa) : « un petit bouton microphone dans l'input du chat pour
parler et que ça écrive sur le chat ».

⚠️ CE QUE CE BANC NE PEUT PAS PROUVER, et il vaut mieux le dire ici que le
laisser croire : la reconnaissance vocale est une API du NAVIGATEUR. Aucun banc
hors navigateur ne peut la faire parler. Ce fichier vérifie donc le CONTRAT —
les choix qui, s'ils sautaient, feraient une fonctionnalité qui a l'air de
marcher et ne marche pas. Le juge final reste un micro et un vrai Chrome.

LES CINQ CHOSES QUI DOIVENT TENIR :
  1. ON APPUIE, ÇA ÉCOUTE ; ON RÉAPPUIE, ÇA S'ARRÊTE — et rien d'autre n'arrête
     l'écoute. Chrome, lui, la coupe tout seul après quelques secondes de
     silence : sans relance, le micro s'éteint au milieu d'une réflexion ;
  2. le bouton n'existe PAS là où le navigateur ne sait pas écouter — un bouton
     présent qui ne fait rien fait croire l'application cassée ;
  3. la voix S'AJOUTE à ce qui était tapé, elle ne l'écrase pas ;
  4. l'écoute s'arrête à l'envoi et au démontage — sinon le micro reste allumé
     et la phrase suivante s'écrit dans un champ déjà vidé ;
  5. une erreur est dite EN FRANÇAIS : « not-allowed » à l'écran n'apprend rien.
"""
import pathlib
import sys

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend")
FRONTEND = BACKEND.resolve().parent / "frontend"
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ DICTÉE — {BACKEND.resolve().parent}\n")

module = FRONTEND / "lib" / "dictee.ts"
if not module.exists():
    print("  ✗ frontend/lib/dictee.ts est absent — la dictée n'existe pas.")
    sys.exit(1)
texte = module.read_text(encoding="utf-8")
barre = (FRONTEND / "components" / "chat" / "InputBar.tsx").read_text(encoding="utf-8")

# ── 1. LE MOTEUR DU NAVIGATEUR ───────────────────────────────────────────
verifier("les deux noms de l'API sont reconnus (Chrome préfixe encore)",
         "SpeechRecognition" in texte and "webkitSpeechRecognition" in texte)
verifier("l'écoute est en français", 'reco.lang = "fr-FR"' in texte)
verifier("l'écoute survit aux respirations (sinon il faut cliquer à chaque phrase)",
         "reco.continuous = true" in texte)
verifier("le texte provisoire s'affiche (sinon on parle devant un champ vide)",
         "reco.interimResults = true" in texte)
verifier("rien n'est tenté côté serveur, où `window` n'existe pas",
         'typeof window === "undefined"' in texte)

# ── 2. LES ERREURS SE DISENT EN FRANÇAIS ─────────────────────────────────
verifier("un micro refusé est expliqué, avec le geste à faire",
         "not-allowed" in texte and "autorisez-le dans votre navigateur" in texte)
verifier("un micro absent est dit", "audio-capture" in texte)
verifier("un silence ou un arrêt volontaire ne fait PAS d'erreur à l'écran",
         '"aborted": ""' in texte and '"no-speech": ""' in texte)

# ── 1bis. LA BASCULE : un appui écoute, un second arrête, RIEN D'AUTRE ────
# Le piège de toute dictée navigateur : Chrome termine la reconnaissance tout
# seul après quelques secondes de silence, `continuous` ou pas. Sans relance,
# le micro s'éteint au milieu d'une réflexion — on reprend la parole devant un
# bouton déjà éteint, et la moitié de la phrase se perd.
verifier("l'écoute se RELANCE quand le navigateur la coupe tout seul",
         "reco.onend" in texte and "if (!voulu)" in texte
         and texte.count("reco.start()") >= 2)
verifier("le texte déjà dicté survit à la relance (elle est invisible)",
         texte.count('acquis = ""') == 2)   # la déclaration, et la remise à zéro au démarrage
verifier("LE SECOND APPUI ARRÊTE POUR DE BON : le drapeau tombe AVANT stop()",
         texte.find("voulu = false\n      try { reco.stop() }") > 0)
verifier("un micro refusé ou absent ne relance PAS en boucle",
         '"not-allowed" || code === "service-not-allowed" || code === "audio-capture"' in texte
         and "voulu = false" in texte)
verifier("un moteur qui ne tient pas ouvert finit par s'arrêter, et le dit",
         "relances > 5" in texte and "n'arrive pas à rester ouverte" in texte)
verifier("aucun code technique ne peut atteindre l'écran",
         "RAISONS[code]" in texte and "La dictée s'est interrompue" in texte)

# ── 3. LE BOUTON ─────────────────────────────────────────────────────────
verifier("le bouton existe dans la barre de saisie",
         'data-testid="dictee"' in barre and "MicIcon" in barre)
verifier("IL N'APPARAÎT PAS là où le navigateur ne sait pas écouter",
         "{micDisponible && (" in barre)
verifier("la disponibilité est lue APRÈS le rendu (sinon l'hydratation diverge)",
         "useEffect(() => { setMicDisponible(dicteeDisponible()) }, [])" in barre)
verifier("un second clic arrête l'écoute", "if (ecoute) {" in barre and "arreter()" in barre)
verifier("l'état d'écoute se voit (bordure) et s'entend des lecteurs d'écran",
         'aria-pressed={ecoute}' in barre and "Arrêter la dictée" in barre)
verifier("le champ dit qu'on écoute", '"Je vous écoute…"' in barre)

# ── 4. CE QUI ÉTAIT TAPÉ N'EST JAMAIS PERDU ──────────────────────────────
verifier("la voix s'AJOUTE à ce qui était déjà écrit",
         "avantDictee.current = texte" in barre
         and "setTexte(avantDictee.current + dit)" in barre)
verifier("l'envoi coupe l'écoute (sinon la phrase suivante part dans le vide)",
         barre.find("dicteeRef.current?.arreter()") < barre.find("onSend(contenu"))
verifier("changer de page éteint le micro",
         "useEffect(() => () => { dicteeRef.current?.arreter() }, [])" in barre)

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)

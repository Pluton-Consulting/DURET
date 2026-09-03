"""
Banc de la DICTÉE — parler plutôt que taper, dans la barre de saisie.

LA DEMANDE (03/09, Noa) : « un petit bouton microphone dans l'input du chat pour
parler et que ça écrive sur le chat » — puis, le soir : « le micro peut
fonctionner, il faut que le transcripteur soit intégré à l'app ».

⚠️ CE QUE CE BANC NE PEUT PAS PROUVER : le micro est une API du NAVIGATEUR.
Aucun banc hors navigateur ne peut enregistrer. Ce fichier vérifie le CONTRAT
côté écran ; la transcription elle-même est prouvée par `test_transcription.py`
(module exécuté contre une API doublée). Le juge final reste un micro et un
vrai navigateur.

LES CINQ CHOSES QUI DOIVENT TENIR :
  1. ON APPUIE, ÇA ÉCOUTE ; ON RÉAPPUIE, ÇA S'ARRÊTE — et rien d'autre n'arrête
     l'écoute (sauf la borne des dix minutes, qui se dit) ;
  2. le navigateur ENREGISTRE, l'application TRANSCRIT : plus de reconnaissance
     vocale du navigateur, qui manquait sur la moitié des postes ;
  3. le texte s'écrit AU FUR ET À MESURE, et la voix S'AJOUTE à ce qui était
     tapé sans jamais l'écraser ;
  4. l'écoute s'arrête à l'envoi et au démontage — sinon le micro reste allumé ;
  5. une erreur est dite EN FRANÇAIS avec le geste à faire, jamais un code.
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
chat = (FRONTEND / "components" / "chat" / "ChatWindow.tsx").read_text(encoding="utf-8")

# ── 1. LE NAVIGATEUR ENREGISTRE, L'APPLICATION TRANSCRIT ──────────────────
verifier("le micro est ouvert par getUserMedia et enregistré par MediaRecorder",
         "getUserMedia({ audio: true })" in texte and "new (window as any).MediaRecorder" in texte)
verifier("PLUS de reconnaissance vocale du navigateur (absente sur la moitié des postes)",
         "webkitSpeechRecognition" not in texte and "reco.lang" not in texte)
verifier("l'enregistrement part à l'application, avec le jeton de session",
         "/api/chat/transcrire" in texte and "Authorization: `Bearer ${options.token}`" in texte)
verifier("le format suit le navigateur (webm/opus partout, mp4 chez Safari)",
         'isTypeSupported' in texte and '"audio/mp4"' in texte)
verifier("le base64 se fabrique par tranches (un gros enregistrement déborderait la pile)",
         "i += 0x8000" in texte)

# ── 2. ÇA S'ÉCRIT AU FUR ET À MESURE ─────────────────────────────────────
verifier("un envoi à cadence régulière pendant l'écoute",
         "CADENCE_MS" in texte and "setInterval(() => { void transcrire(false) }, CADENCE_MS)" in texte)
verifier("chaque envoi porte TOUT depuis le début (un mot coupé à la frontière ne se perd pas)",
         "new Blob(morceaux" in texte and "enr.start(1000)" in texte)
verifier("rien de neuf depuis le dernier envoi = pas d'appel (on ne paie pas pour rien)",
         "morceaux.length === dernierEnvoye" in texte)
# 03/09 (Noa) : « quand on clique pour arrêter il y a du délai le temps qu'il
# finisse d'écrire ». Le bouton se relâche À L'INSTANT du clic ; la dernière
# transcription arrive en arrière-plan, et « je transcris » le dit.
verifier("l'arrêt relâche le bouton TOUT DE SUITE, la version définitive part en arrière-plan",
         "options.surFin()\n        void transcrire(true)" in texte)
verifier("une réponse plus ancienne n'écrase jamais une plus récente (numéro d'ordre)",
         "if (mien < applique) return" in texte and "applique = mien" in texte)
verifier("« je transcris » ne s'éteint qu'avec le DERNIER envoi en vol",
         "options.surTravail?.(enVol > 0)" in texte)
verifier("la barre dit qu'elle transcrit la fin, une fois l'écoute arrêtée",
         '"Je transcris la fin de la dictée…"' in barre and "surFin: () => setEcoute(false)," in barre)

# ── 3. LA BASCULE : un appui écoute, un second arrête ────────────────────
verifier("un drapeau d'intention fait foi", "let voulu = false" in texte and "if (!voulu) return" in texte)
verifier("le second appui arrête pour de bon (pistes coupées, horloges arrêtées)",
         "getTracks().forEach((t) => t.stop())" in texte and "clearInterval(horloge)" in texte)
verifier("dix minutes au plus, et la borne SE DIT",
         "DUREE_MAX_MS = 10 * 60 * 1000" in texte and "Dix minutes de dictée" in texte)

# ── 4. LES ERREURS SE DISENT EN FRANÇAIS ─────────────────────────────────
verifier("un micro refusé est expliqué, avec le geste à faire",
         "NotAllowedError" in texte and "autorisez-le dans votre navigateur" in texte)
verifier("un micro absent est dit", "NotFoundError" in texte and "Aucun micro" in texte)
verifier("l'adresse en http est nommée (le micro exige https)",
         "isSecureContext" in texte and "adresse sécurisée (https)" in texte)
verifier("l'ancien message faux (« ce navigateur ne sait pas transcrire ») a disparu",
         "Chrome, Edge ou Safari le savent" not in texte)
verifier("une session expirée arrête la dictée au lieu de tourner à vide",
         "if (res.status === 401) arreter()" in texte)

# ── 5. LE BOUTON ET LE CHAMP ─────────────────────────────────────────────
verifier("le bouton existe, toujours, et c'est le clic qui explique",
         'data-testid="dictee"' in barre and "raisonIndisponible()" in barre and "micDisponible" not in barre)
verifier("la barre reçoit le jeton de session depuis le chat",
         "token={token}" in chat and "token?: string" in barre)
verifier("sans jeton, on le dit au lieu d'échouer en silence",
         "Session absente : rechargez la page" in barre)
verifier("la voix s'AJOUTE à ce qui était déjà écrit (repère avant dictée)",
         "avantDictee.current = texte" in barre and "setTexte(avantDictee.current + dit)" in barre)
verifier("le champ dit qu'on écoute, et quand on transcrit",
         '"Je vous écoute…"' in barre and "(je transcris)" in barre)
verifier("l'envoi coupe l'écoute (sinon la phrase suivante part dans le vide)",
         barre.find("dicteeRef.current?.arreter()") < barre.find("onSend(contenu"))
verifier("changer de page éteint le micro",
         "useEffect(() => () => { dicteeRef.current?.arreter() }, [])" in barre)

# ── 6. LA SAISIE : quatre lignes, puis on défile ─────────────────────────
verifier("la hauteur est BORNÉE à QUATRE lignes",
         "LIGNES_VISIBLES = 4" in barre and "ligne * LIGNES_VISIBLES" in barre)
verifier("là où le navigateur sait grandir seul, on le laisse faire et on ne pose que le plafond",
         'CSS.supports?.("field-sizing", "content")' in barre and 'champ.style.maxHeight = `${plafond}px`' in barre)
verifier("ailleurs, la hauteur est mesurée à chaque frappe, et redescend quand on efface",
         'champ.style.height = "auto"' in barre
         and 'champ.style.overflowY = champ.scrollHeight > plafond ? "auto" : "hidden"' in barre)
verifier("la mesure a lieu AVANT le dessin (pas de saut visible)", "useLayoutEffect(() => {" in barre)
verifier("le champ part d'une ligne", "rows={1}" in barre)
verifier("un raccourci prérempli met le curseur À LA FIN, champ déroulé",
         "setSelectionRange(r.prompt.length, r.prompt.length)" in barre
         and "champ.scrollTop = champ.scrollHeight" in barre)

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)

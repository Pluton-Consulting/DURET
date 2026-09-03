/**
 * LA DICTÉE — parler plutôt que taper, dans la barre de saisie.
 *
 * Demande de Noa (03/09) : « un petit bouton microphone dans l'input du chat
 * pour parler et que ça écrive sur le chat ».
 *
 * CE QUE ÇA UTILISE, ET CE QUE ÇA VEUT DIRE. La reconnaissance vocale du
 * NAVIGATEUR (`SpeechRecognition`), pas un service que nous appellerions : rien
 * à installer, aucune clé, aucun coût, et le son ne traverse pas notre backend.
 * ⚠️ En revanche, sur Chrome et Edge, le navigateur envoie l'audio aux serveurs
 * de Google pour le transcrire — exactement comme la dictée du téléphone. Ce
 * n'est pas une fuite de NOS données (rien de la base ne part), mais c'est la
 * voix de la personne : à dire au client, et c'est pourquoi le bouton ne
 * s'active jamais tout seul.
 *
 * QUAND LE NAVIGATEUR NE SAIT PAS (Firefox, notamment), le bouton n'existe
 * pas. Un bouton présent qui ne fait rien est pire que pas de bouton : on
 * clique, on parle, il ne se passe rien, et on croit que l'application est
 * cassée.
 *
 * LE TEXTE PROVISOIRE COMPTE. La reconnaissance rend d'abord une hypothèse
 * (`interimResults`), puis la corrige. Sans elle, on parle dix secondes devant
 * un champ vide et l'on croit que rien n'est entendu. On affiche donc le
 * provisoire, remplacé par le définitif dès qu'il arrive.
 */

/** L'objet du navigateur, sous ses deux noms (Chrome le préfixe encore). */
function moteur(): any {
  if (typeof window === "undefined") return null
  return (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition || null
}

/** Le navigateur sait-il écouter ? Sert à MONTRER ou non le bouton. */
export function dicteeDisponible(): boolean {
  return moteur() !== null
}

export interface Dictee {
  /** Commence à écouter. */
  demarrer: () => void
  /** Arrête — ce que fait le second clic, et l'envoi du message. */
  arreter: () => void
}

export interface OptionsDictee {
  /** Le texte reconnu depuis le début de cette dictée, provisoire compris. */
  surTexte: (texte: string, definitif: boolean) => void
  /** L'écoute s'est arrêtée (fin de phrase, clic, ou erreur). */
  surFin: () => void
  /** Un souci à dire à l'utilisateur, en français, sans mot de tuyauterie. */
  surErreur: (message: string) => void
}

// Les codes rendus par le navigateur, traduits en phrases utiles. Un code brut
// (« not-allowed ») affiché tel quel n'apprend rien à personne.
const RAISONS: Record<string, string> = {
  "not-allowed": "Le micro est bloqué pour ce site : autorisez-le dans votre navigateur, puis réessayez.",
  "service-not-allowed": "Le micro est bloqué pour ce site : autorisez-le dans votre navigateur, puis réessayez.",
  "audio-capture": "Aucun micro n'a été trouvé sur cet appareil.",
  "network": "La reconnaissance vocale n'a pas pu joindre son service. Vérifiez la connexion.",
  "aborted": "",   // c'est nous qui avons arrêté : rien à dire
  "no-speech": "",  // silence : on s'arrête, sans reproche
}

/**
 * Prépare une dictée. Rend `null` si le navigateur ne sait pas écouter.
 *
 * Le texte rendu est TOUJOURS celui de la dictée entière depuis `demarrer()` :
 * c'est à l'appelant de décider où le poser (ici, à la suite de ce qui était
 * déjà tapé). Recoller les morceaux ici aurait obligé chaque appelant à
 * dédoublonner les segments corrigés par le moteur.
 */
export function creerDictee(options: OptionsDictee): Dictee | null {
  const Moteur = moteur()
  if (!Moteur) return null

  const reco = new Moteur()
  reco.lang = "fr-FR"
  // On garde l'écoute ouverte entre deux phrases : sans cela, la
  // reconnaissance s'arrête à la première respiration, et dicter un paragraphe
  // demande de cliquer dix fois.
  reco.continuous = true
  reco.interimResults = true

  let acquis = ""      // ce que le moteur a définitivement reconnu
  let vivant = false

  reco.onresult = (evenement: any) => {
    let provisoire = ""
    for (let i = evenement.resultIndex; i < evenement.results.length; i++) {
      const morceau = evenement.results[i]
      if (morceau.isFinal) acquis += morceau[0].transcript
      else provisoire += morceau[0].transcript
    }
    options.surTexte((acquis + provisoire).trim(), provisoire === "")
  }

  reco.onerror = (evenement: any) => {
    const raison = RAISONS[evenement?.error] ?? "La dictée s'est interrompue. Réessayez."
    if (raison) options.surErreur(raison)
  }

  reco.onend = () => {
    vivant = false
    options.surFin()
  }

  return {
    demarrer() {
      if (vivant) return
      acquis = ""
      try {
        reco.start()
        vivant = true
      } catch {
        // `start()` sur une instance déjà démarrée lève : ce n'est pas une
        // panne, l'écoute est en cours et c'est ce qu'on voulait.
        vivant = true
      }
    },
    arreter() {
      try { reco.stop() } catch { /* déjà arrêtée */ }
      vivant = false
    },
  }
}

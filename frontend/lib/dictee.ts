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
 * ON APPUIE, ÇA ÉCOUTE ; ON RÉAPPUIE, ÇA S'ARRÊTE. Rien d'autre n'arrête
 * l'écoute — et ce n'est pas gratuit : Chrome termine la reconnaissance tout
 * seul après quelques secondes de silence, `continuous` ou pas. On la relance
 * donc en silence (`onend`), sans perdre le texte déjà dicté. Sans cela, le
 * micro s'éteignait au milieu d'une réflexion.
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

/**
 * Pourquoi la dictée ne peut pas fonctionner ici — ou `null` si tout va bien.
 *
 * POURQUOI CETTE FONCTION A REMPLACÉ UN SIMPLE « disponible ou non » (03/09,
 * relevé de Noa : « le bouton vocal ne s'affiche pas »). Cacher le bouton
 * quand l'API manque paraissait propre ; en pratique c'est le pire des
 * comportements — il ne se passe RIEN, et personne ne peut deviner si c'est le
 * navigateur, l'adresse, ou l'application qui est en retard. Le bouton reste
 * donc toujours là, et c'est le clic qui explique.
 *
 * DEUX CAUSES, DEUX PHRASES. La reconnaissance vocale n'existe QUE dans un
 * contexte sécurisé : ouverte en `http://` (par une adresse IP du VPN, par
 * exemple), Chrome n'expose même pas l'objet — d'où un bouton qui semblait
 * cassé sur le serveur alors qu'il marchait sur le poste de développement.
 */
export function raisonIndisponible(): string | null {
  if (moteur()) return null
  if (typeof window !== "undefined" && (window as any).isSecureContext === false) {
    return "La dictée demande une adresse sécurisée (https). Ouvrez l'application "
      + "par son adresse https, puis réessayez."
  }
  return "Ce navigateur ne sait pas transcrire la voix. Chrome, Edge ou Safari le savent."
}

export interface Dictee {
  /** Commence à écouter, et NE S'ARRÊTE PLUS avant `arreter()`. */
  demarrer: () => void
  /** Arrête pour de bon — ce que fait le second appui, et l'envoi du message. */
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
  "no-speech": "",  // un silence n'est pas une faute : on relance, sans rien dire
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
  // L'UTILISATEUR A APPUYÉ, ET N'A PAS ENCORE RÉAPPUYÉ. C'est CE drapeau qui
  // fait foi, pas l'état du moteur : voir `onend` ci-dessous.
  let voulu = false
  let relances = 0
  let derniereRelance = 0

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
    const code = evenement?.error
    // TROIS REFUS SUR LESQUELS IL EST INUTILE D'INSISTER : pas d'autorisation,
    // pas de micro. Sans cette ligne, la relance automatique de `onend`
    // rouvrirait l'écoute aussitôt, en boucle, et la personne verrait le même
    // message revenir sans fin.
    if (code === "not-allowed" || code === "service-not-allowed" || code === "audio-capture") {
      voulu = false
    }
    const raison = RAISONS[code] ?? "La dictée s'est interrompue. Réessayez."
    if (raison) options.surErreur(raison)
  }

  reco.onend = () => {
    // ON APPUIE, ÇA ÉCOUTE ; ON RÉAPPUIE, ÇA S'ARRÊTE — et RIEN D'AUTRE ne
    // doit arrêter l'écoute.
    //
    // Chrome termine la reconnaissance TOUT SEUL après quelques secondes de
    // silence, `continuous` ou pas. Sans la relance ci-dessous, le micro
    // s'éteignait au milieu d'une réflexion : on reprenait la parole devant un
    // bouton déjà éteint, et la moitié de la phrase se perdait. `acquis` n'est
    // PAS remis à zéro ici — la relance est invisible, le texte continue.
    if (!voulu) {
      options.surFin()
      return
    }
    // Garde-fou : si le moteur se ferme aussitôt rouvert, plusieurs fois de
    // suite, c'est qu'il ne peut pas écouter. On s'arrête et on le dit, plutôt
    // que de tourner en rond en silence.
    const maintenant = Date.now()
    relances = maintenant - derniereRelance < 1000 ? relances + 1 : 0
    derniereRelance = maintenant
    if (relances > 5) {
      voulu = false
      options.surErreur("La dictée n'arrive pas à rester ouverte. Vérifiez le micro, puis réessayez.")
      options.surFin()
      return
    }
    try {
      reco.start()
    } catch {
      voulu = false
      options.surFin()
    }
  }

  return {
    demarrer() {
      if (voulu) return
      acquis = ""
      relances = 0
      voulu = true
      try {
        reco.start()
      } catch {
        // `start()` sur une instance déjà démarrée lève : ce n'est pas une
        // panne, l'écoute est en cours et c'est ce qu'on voulait.
      }
    },
    arreter() {
      // Le drapeau AVANT l'arrêt : `stop()` déclenche `onend`, qui relancerait
      // l'écoute si le drapeau était encore levé — le second appui n'arrêterait
      // alors rien du tout.
      voulu = false
      try { reco.stop() } catch { /* déjà arrêtée */ }
    },
  }
}

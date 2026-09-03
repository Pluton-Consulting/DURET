/**
 * LA DICTÉE — parler plutôt que taper, dans la barre de saisie.
 *
 * Demande de Noa (03/09) : « un petit bouton microphone dans l'input du chat
 * pour parler et que ça écrive sur le chat ». Puis, le soir même, après une
 * première version : « le micro peut fonctionner, il faut que le transcripteur
 * soit intégré à l'app ».
 *
 * CE QUI A CHANGÉ DE CAMP. La première version s'en remettait à la
 * reconnaissance vocale du NAVIGATEUR (`SpeechRecognition`) : sans clé, sans
 * serveur — et absente sur la moitié des postes (Firefox, Chromium sans les
 * services Google, certains Chrome d'entreprise). Le bouton répondait « ce
 * navigateur ne sait pas transcrire la voix » sur un poste dont le micro
 * marchait très bien. Désormais le navigateur ne fait qu'ENREGISTRER
 * (`MediaRecorder`, que tous savent faire), et c'est L'APPLICATION qui
 * transcrit (`POST /api/chat/transcrire`, modèle Google déjà payé pour la
 * vision). Le son passe par notre serveur, plus par celui de Google via le
 * navigateur : il est transcrit puis oublié.
 *
 * ON APPUIE, ÇA ÉCOUTE ; ON RÉAPPUIE, ÇA S'ARRÊTE. Entre les deux, le texte
 * S'ÉCRIT AU FUR ET À MESURE : toutes les quelques secondes, l'enregistrement
 * depuis le début est envoyé et le texte rendu REMPLACE le précédent (une
 * transcription se corrige elle-même en entendant la suite). Envoyer le tout
 * plutôt que le dernier morceau, c'est ce qui évite qu'un mot coupé à la
 * frontière de deux morceaux disparaisse. Dix minutes au plus : au-delà, ce
 * n'est plus une dictée, c'est une réunion — et le compte rendu de réunion
 * prend une transcription écrite.
 */

export interface Dictee {
  /** Commence à écouter, et NE S'ARRÊTE PLUS avant `arreter()`. */
  demarrer: () => Promise<void>
  /** Arrête pour de bon — ce que fait le second appui, et l'envoi du message. */
  arreter: () => void
}

export interface OptionsDictee {
  /** Où envoyer l'enregistrement, et avec quel jeton. */
  apiUrl: string
  token: string
  /** Le texte transcrit depuis le début de cette dictée (remplace le précédent). */
  surTexte: (texte: string, definitif: boolean) => void
  /** L'écoute s'est arrêtée (clic, erreur, ou la borne des dix minutes). */
  surFin: () => void
  /** Un souci à dire à l'utilisateur, en français, sans mot de tuyauterie. */
  surErreur: (message: string) => void
  /** Une transcription est en cours (pour dire « je transcris… »). */
  surTravail?: (enCours: boolean) => void
}

// Cadence des envois pendant l'écoute, et borne d'une dictée.
const CADENCE_MS = 6000
const DUREE_MAX_MS = 10 * 60 * 1000

/**
 * Pourquoi la dictée ne peut pas fonctionner ici — ou `null` si tout va bien.
 *
 * Le bouton reste TOUJOURS là, et c'est le clic qui explique : un bouton
 * absent ne dit rien, et l'on cherche du côté de l'application. Deux causes
 * réelles, deux phrases : l'adresse en `http://` (le micro n'est accordé
 * qu'en contexte sécurisé), ou un navigateur sans enregistrement audio — ce
 * qui, en 2026, ne se voit plus guère.
 */
export function raisonIndisponible(): string | null {
  if (typeof window === "undefined") return "La dictée ne fonctionne que dans le navigateur."
  if ((window as any).isSecureContext === false) {
    return "Le micro demande une adresse sécurisée (https). Ouvrez l'application "
      + "par son adresse https, puis réessayez."
  }
  if (!navigator.mediaDevices?.getUserMedia || typeof (window as any).MediaRecorder === "undefined") {
    return "Ce navigateur ne sait pas enregistrer le micro. Mettez-le à jour, ou utilisez Chrome, Edge, Firefox ou Safari."
  }
  return null
}

/** Le format que ce navigateur sait produire — webm/opus partout, sauf Safari (mp4). */
function formatEnregistrement(): string {
  const MR = (window as any).MediaRecorder
  const candidats = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"]
  for (const c of candidats) {
    try { if (MR.isTypeSupported?.(c)) return c } catch { /* on essaie le suivant */ }
  }
  return ""
}

async function enBase64(blob: Blob): Promise<string> {
  const tampon = await blob.arrayBuffer()
  const octets = new Uint8Array(tampon)
  let s = ""
  // Par tranches : `String.fromCharCode(...octets)` déborde la pile au-delà
  // de quelques centaines de kilo-octets.
  for (let i = 0; i < octets.length; i += 0x8000) {
    s += String.fromCharCode.apply(null, Array.from(octets.subarray(i, i + 0x8000)))
  }
  return btoa(s)
}

/**
 * Prépare une dictée. Rend `null` si le navigateur ne sait pas enregistrer.
 *
 * Le texte rendu est TOUJOURS celui de la dictée entière depuis `demarrer()` :
 * c'est à l'appelant de décider où le poser (ici, à la suite de ce qui était
 * déjà tapé).
 */
export function creerDictee(options: OptionsDictee): Dictee | null {
  if (raisonIndisponible()) return null

  let flux: MediaStream | null = null
  let enregistreur: MediaRecorder | null = null
  const morceaux: Blob[] = []
  let mime = ""
  let voulu = false
  let horloge: ReturnType<typeof setInterval> | null = null
  let butoir: ReturnType<typeof setTimeout> | null = null
  let envoiEnCours = false
  let dernierEnvoye = 0        // combien de morceaux couvrait le dernier envoi
  // Numéro d'ordre des envois : une réponse plus ANCIENNE qu'une déjà
  // appliquée ne doit pas écraser le texte (l'envoi définitif part sans
  // attendre l'intermédiaire en vol ; les deux peuvent revenir dans le
  // désordre).
  let numero = 0
  let applique = 0
  let enVol = 0                // envois en cours : « je transcris » tant qu'il en reste un

  const transcrire = async (definitif: boolean) => {
    // Rien de neuf depuis le dernier envoi : inutile de payer un appel.
    if (morceaux.length === 0 || (!definitif && morceaux.length === dernierEnvoye)) return
    if (envoiEnCours && !definitif) return
    envoiEnCours = true
    enVol += 1
    options.surTravail?.(true)
    const couvert = morceaux.length
    const mien = ++numero
    try {
      const blob = new Blob(morceaux, { type: mime || "audio/webm" })
      const audio_b64 = await enBase64(blob)
      const res = await fetch(`${options.apiUrl}/api/chat/transcrire`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${options.token}` },
        body: JSON.stringify({ audio_b64, mime: mime || "audio/webm" }),
      })
      const d = await res.json().catch(() => ({}))
      if (!res.ok) {
        options.surErreur(d.detail || "La transcription n'a pas abouti. Réessayez.")
        if (res.status === 401) arreter()
        return
      }
      if (mien < applique) return          // une réponse plus récente est déjà à l'écran
      applique = mien
      dernierEnvoye = couvert
      options.surTexte(String(d.texte || "").trim(), definitif)
    } catch {
      options.surErreur("Le serveur n'a pas répondu pendant la transcription. Réessayez.")
    } finally {
      envoiEnCours = false
      enVol -= 1
      // L'envoi définitif peut finir AVANT un intermédiaire encore en vol :
      // « je transcris » ne s'éteint qu'avec le dernier.
      options.surTravail?.(enVol > 0)
    }
  }

  const liberer = () => {
    if (horloge) { clearInterval(horloge); horloge = null }
    if (butoir) { clearTimeout(butoir); butoir = null }
    try { flux?.getTracks().forEach((t) => t.stop()) } catch { /* déjà coupé */ }
    flux = null
    enregistreur = null
  }

  const arreter = () => {
    if (!voulu) return
    voulu = false
    const enr = enregistreur
    // LE BOUTON SE RELÂCHE TOUT DE SUITE (03/09, relevé de Noa : « quand on
    // clique pour arrêter il y a du délai le temps qu'il finisse d'écrire »).
    // L'écoute est finie à l'instant du clic ; la DERNIÈRE transcription,
    // elle, arrive quand elle arrive — le champ dit « je transcris » pendant
    // ce temps, et le texte se complète à son arrivée. Attendre le serveur
    // pour relâcher le bouton faisait croire que le clic n'avait pas pris.
    if (enr && enr.state !== "inactive") {
      // `stop()` livre le dernier morceau PUIS déclenche `onstop` : c'est là
      // qu'on envoie la version définitive, complète — en arrière-plan.
      enr.onstop = () => {
        liberer()
        options.surFin()
        void transcrire(true)
      }
      try { enr.stop() } catch { liberer(); options.surFin() }
    } else {
      liberer()
      options.surFin()
    }
  }

  const demarrer = async () => {
    if (voulu) return
    voulu = true
    morceaux.length = 0
    dernierEnvoye = 0
    try {
      flux = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch (e: any) {
      voulu = false
      const nom = String(e?.name || "")
      options.surErreur(
        nom === "NotAllowedError" || nom === "SecurityError"
          ? "Le micro est bloqué pour ce site : autorisez-le dans votre navigateur, puis réessayez."
          : nom === "NotFoundError"
          ? "Aucun micro n'a été trouvé sur cet appareil."
          : "Le micro n'a pas pu être ouvert. Réessayez.")
      options.surFin()
      return
    }
    mime = formatEnregistrement()
    try {
      enregistreur = new (window as any).MediaRecorder(flux, mime ? { mimeType: mime } : undefined)
    } catch {
      liberer(); voulu = false
      options.surErreur("Ce navigateur ne sait pas enregistrer le micro dans un format lisible.")
      options.surFin()
      return
    }
    const enr = enregistreur!
    mime = enr.mimeType || mime
    enr.ondataavailable = (ev: BlobEvent) => { if (ev.data && ev.data.size > 0) morceaux.push(ev.data) }
    enr.onerror = () => { options.surErreur("L'enregistrement s'est interrompu. Réessayez."); arreter() }
    // Un morceau par seconde : c'est ce qui permet d'envoyer « tout depuis le
    // début » à intervalle régulier sans attendre la fin.
    enr.start(1000)
    horloge = setInterval(() => { void transcrire(false) }, CADENCE_MS)
    butoir = setTimeout(() => {
      options.surErreur("Dix minutes de dictée : c'est la limite. Réappuyez pour continuer sur une nouvelle dictée.")
      arreter()
    }, DUREE_MAX_MS)
  }

  return { demarrer, arreter }
}

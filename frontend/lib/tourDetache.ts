// LE TOUR DU CHAT QUI SURVIT À LA NAVIGATION.
//
// Ouvrir Paramètres (ou n'importe quelle autre section) démonte le composant
// du chat. Avant ce module, le démontage fermait la socket ; or le serveur
// ANNULE le tour quand sa socket se ferme — et le repli POST du composant
// relançait en plus la même demande en double, en aveugle. Résultat observé :
// « si je vais dans les paramètres pendant qu'une demande est en cours, ça la
// stoppe ».
//
// L'idée : dans une SPA, le runtime JavaScript survit à la navigation. La
// connexion WebSocket et les closures qui la servent peuvent donc continuer à
// vivre pendant que l'écran est absent. Ce module ne porte QUE le petit état
// partagé qui permet de re-brancher l'écran au retour : quel fil, quelle
// question, où en est le travail — et la socket, pour que le bouton d'arrêt
// fonctionne encore après un aller-retour.
//
// Une seule place : le chat ne mène qu'un tour principal à la fois (les tâches
// déplacées en carte et la file d'attente ont leur propre suivi, côté serveur).
// Après un vrai rechargement de page (F5), ce module repart vide : c'est alors
// le serveur qui tient la promesse — le tour détaché s'y termine et sa réponse
// est écrite dans l'historique de la conversation.

export interface TourDetache {
  threadId: string
  question: string
  activite: string
  // La socket du tour, si elle vit encore : le bouton « arrêter » la retrouve.
  ws?: WebSocket | null
  // Le tour s'est achevé pendant l'absence. Pas de réponse ici : le serveur
  // l'a persistée AVANT de l'annoncer, l'écran la relit dans l'historique.
  fini?: boolean
  // Une action attend un accord (l'identifiant de la validation, s'il est connu).
  suspendu?: string | null
}

let courant: TourDetache | null = null
let abonne: ((t: TourDetache) => void) | null = null

/** Le composant se démonte avec un tour en vol : il le confie au module. */
export function detacherTour(t: TourDetache): void {
  courant = t
}

/** Les closures du tour (toujours vivantes) publient leur progression ici. */
export function majTourDetache(patch: Partial<TourDetache>): void {
  if (!courant) return
  Object.assign(courant, patch)
  abonne?.(courant)
}

/** Au montage : le tour détaché de CE fil, s'il y en a un. Ne consomme rien. */
export function reprendreTour(threadId: string | null): TourDetache | null {
  if (!courant || !threadId || courant.threadId !== threadId) return null
  return courant
}

/** Le tour est soldé (affiché, suspendu repris, ou abandonné) : on oublie. */
export function terminerTourDetache(): void {
  courant = null
}

/** Un seul écran écoute à la fois : le dernier monté remplace le précédent. */
export function abonnerTour(fn: (t: TourDetache) => void): () => void {
  abonne = fn
  return () => { if (abonne === fn) abonne = null }
}

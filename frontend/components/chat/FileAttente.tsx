"use client"
// Le bas de la colonne de droite : les taches en arriere-plan et les accords
// en attente. C'est ce qui permet de lancer plusieurs demandes de front, de
// fermer l'onglet, et de valider une action plusieurs jours apres — tout ce
// qui s'affiche ici vit en base, rien ne depend de la page ouverte.
//
// POURQUOI CES CARTES NE SONT PAS PASSÉES SUR `Tool` OU `Task` (AI Elements).
//
// `Tool` affiche l'état par un libellé figé, écrit en dur dans le composant,
// en anglais, et non surchargeable : « Completed » pour tout ce qui se
// termine. Or ici le texte d'une tâche achevée vient du BACKEND, et une
// action refusée revient avec « refusée — rien n'a été fait ». La remplacer
// par « Completed » ferait passer un refus pour un succès — sur l'écran même
// où l'on valide des actions engageantes. C'est le seul endroit de
// l'application où un libellé approximatif a une conséquence réelle.
//
// `Task`, lui, n'a aucun état : ni prop `status`, ni `state`. C'est un
// dépliant décoratif. Il ne peut pas porter les cinq états d'une tâche
// (en cours, attente d'accord, terminée, échec, interrompue).
//
// Les boutons viennent en revanche du même jeu de primitives que le reste.

import { Callout, KeyValueTable, PrimaryButton, GhostButton } from "@/components/blocks"

export interface TacheFond {
  id: string
  // "ws" : la tache principale du chat, dont l'ecran a ete cede a une plus
  // recente — elle continue sur sa connexion, seule sa carte bouge ici.
  // "file" : une tache differee cote backend, suivie par sondage.
  source: "ws" | "file"
  question: string
  etat: "en_cours" | "terminee" | "echec" | "interrompue" | "attente_validation"
  activite: string
  // Reponse presente pour les taches "ws" (recue par leur connexion) ; les
  // taches "file" la chargent au clic, elle ne voyage pas dans le sondage.
  reponse?: string
  erreur?: string
  validationId?: string
}

export interface AccordEnAttente {
  id: string
  motif?: string | null
  skill?: string | null
  args?: Record<string, any> | null
}

// Ce que l'action va faire, dit en francais : le nom technique n'apprend rien
// a qui doit decider s'il l'autorise.
const ACTIONS_EXTERNES: Record<string, string> = {
  nas_deposer: "Déposer un fichier sur le serveur de l'entreprise",
  nas_deposer_document: "Finaliser un document et le déposer sur le serveur",
  generer_visuel: "Générer un visuel (cette génération est facturée)",
  rediger_email: "Envoyer un message",
  redaction_email: "Envoyer un message",
}

const REPERES: [string, string][] = [
  ["dossier", "Dossier"],
  ["chemin", "Chemin"],
  ["nom", "Nom du fichier"],
  ["destinataire", "Destinataire"],
  ["titre", "Titre"],
  ["format", "Format"],
]

function decrire(v: AccordEnAttente): { titre: string; lignes: [string, string][] } {
  const titre = (v.skill && ACTIONS_EXTERNES[v.skill]) || v.motif || "Action à effet externe"
  const a = v.args || {}
  const lignes = REPERES
    .filter(([cle]) => a[cle] !== undefined && a[cle] !== null && a[cle] !== "")
    .map(([cle, etiquette]) => [etiquette, String(a[cle])] as [string, string])
  return { titre, lignes }
}

interface Props {
  taches: TacheFond[]
  accords: AccordEnAttente[]
  accordEnCours: string | null            // id en cours de resolution (barre discrete)
  // L'erreur porte l'id de la carte concernee : rattachee au seul « en cours »,
  // elle n'etait JAMAIS visible — cet indicateur retombe a null dans le meme
  // lot de rendu que le message, donc la condition etait fausse des le premier
  // affichage. Un bouton qui echoue sans rien dire se lit comme un bouton casse.
  erreurAccord: { id: string; message: string } | null
  // Le role de la personne permet-il de trancher ? Les accords sont servis au
  // DEMANDEUR, mais seul un valideur peut les resoudre.
  peutDecider: boolean
  onAfficher: (t: TacheFond) => void      // clic sur une carte terminee
  onFermer: (t: TacheFond) => void        // croix d'une carte close
  onArreter?: (t: TacheFond) => void      // arrêt d'une tâche en cours
  onResoudre: (id: string, approuve: boolean) => void
}

const ETAT_LIBELLE: Record<string, string> = {
  echec: "Échec",
  interrompue: "Interrompue par un redémarrage",
}

export default function FileAttente({ taches, accords, accordEnCours, erreurAccord,
                                      peutDecider, onAfficher, onFermer, onArreter,
                                      onResoudre }: Props) {
  if (!taches.length && !accords.length) return null

  return (
    <div className="sym-file" data-testid="file-attente">
      <style>{`
        /* Glissement de gauche a droite : la tache « quitte » le chat pour la
           colonne. La direction du mouvement raconte ce qui s'est passe. */
        @keyframes symGlisse { from { transform: translateX(-26px); opacity: 0 }
                               to { transform: none; opacity: 1 } }
        /* Barre discrete et indeterminee : on ne connait pas la duree d'un tour
           de modele, une fausse progression chiffree serait un mensonge. */
        @keyframes symBarre { 0% { left: -34% } 100% { left: 104% } }
        .sym-file{ display:flex; flex-direction:column; gap:10px; padding-top:14px;
          border-top:1px solid var(--marque-border); }
        .sym-file-titre{ font-size:11px; letter-spacing:.14em; text-transform:uppercase;
          color:var(--marque-primary-mid); font-weight:700; }
        .sym-carte{ position:relative; background:var(--marque-surface);
          border:1px solid var(--marque-border); border-radius:var(--marque-radius-card-sm);
          padding:10px 12px; box-shadow:var(--marque-shadow-card);
          animation: symGlisse .35s cubic-bezier(.22,.61,.36,1) both; }
        .sym-carte.cliquable{ cursor:pointer; transition:border-color .2s ease, box-shadow .2s ease; }
        .sym-carte.cliquable:hover{ border-color:var(--marque-primary-light); box-shadow:var(--marque-shadow-hover); }
        .sym-carte-q{ font-size:12.5px; font-weight:600; color:var(--marque-text-primary);
          overflow:hidden; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical;
          padding-right:18px; }
        .sym-carte-etat{ font-size:11.5px; color:var(--marque-text-muted); margin-top:5px; }
        .sym-carte-stop{ margin-top:8px; font-size:11.5px; font-weight:600;
          color:var(--marque-error-text); background:transparent; cursor:pointer;
          border:1px solid var(--marque-error-text); border-radius:var(--marque-radius-pill);
          padding:3px 12px; }
        .sym-carte-stop:hover{ background:var(--marque-error-text); color:#fff; }
        .sym-carte-etat.ok{ color:var(--marque-paid-text); font-weight:600; }
        .sym-carte-etat.ko{ color:var(--marque-error-text); }
        .sym-piste{ position:relative; height:3px; margin-top:8px; border-radius:2px;
          overflow:hidden; background:var(--marque-primary-subtle); }
        .sym-piste i{ position:absolute; top:0; width:30%; height:100%; border-radius:2px;
          background:linear-gradient(90deg, var(--marque-primary-light), var(--marque-primary-mid));
          animation: symBarre 1.3s ease-in-out infinite; }
        .sym-croix{ position:absolute; top:6px; right:8px; border:none; background:none;
          color:var(--marque-text-muted); font-size:14px; line-height:1; cursor:pointer;
          padding:2px 4px; font-weight:700; }
        @media (prefers-reduced-motion: reduce){ .sym-carte{ animation:none }
          .sym-piste i{ animation:none; width:100% } }
      `}</style>

      <div className="sym-file-titre">En arrière-plan</div>

      {/* Les accords d'abord : c'est ce qui ATTEND l'humain, le reste avance seul. */}
      {accords.map((v) => {
        const { titre, lignes } = decrire(v)
        const occupe = accordEnCours === v.id
        const erreur = erreurAccord && erreurAccord.id === v.id ? erreurAccord.message : null
        return (
          <div key={v.id} className="sym-carte" data-testid="carte-accord"
               role="group" aria-label="Action en attente de votre décision"
               style={{ borderColor: "var(--marque-pending-text)" }}>
            <Callout tone="warning" title="Votre accord est nécessaire">{titre}</Callout>
            {lignes.length > 0 && <div style={{ marginTop: 8 }}><KeyValueTable rows={lignes} /></div>}
            {erreur && (
              <div style={{ marginTop: 8 }}><Callout tone="error">{erreur}</Callout></div>
            )}
            {occupe ? (
              // La decision est partie : la reprise du tour peut prendre
              // plusieurs secondes (elle EXECUTE l'action). Barre discrete,
              // boutons retires — un second clic enverrait deux decisions.
              <div className="sym-piste" aria-label="Exécution en cours"><i /></div>
            ) : peutDecider ? (
              <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
                <PrimaryButton size="sm" onClick={() => onResoudre(v.id, true)}>Approuver</PrimaryButton>
                <GhostButton danger onClick={() => onResoudre(v.id, false)}>Refuser</GhostButton>
              </div>
            ) : (
              // Sans le droit de trancher, deux boutons qui echouent a chaque
              // clic valent moins qu'une phrase qui dit quoi faire.
              <div className="sym-carte-etat" style={{ marginTop: 8 }}>
                Une personne de la direction doit approuver cette action.
              </div>
            )}
          </div>
        )
      })}

      {taches.map((t) => {
        // Une tache "file" terminee est cliquable meme sans reponse chargee :
        // le clic ira la chercher. Une "ws" porte deja la sienne.
        const finie = t.etat === "terminee"
        // La croix existe AUSSI sur une carte en attente d'accord : si la
        // reprise echoue, la validation n'est plus « pending », sa carte
        // disparait, et celle-ci resterait « en attente de votre accord
        // ci-dessus » avec plus rien au-dessus — sans aucune issue.
        const close = t.etat !== "en_cours"
        return (
          <div key={t.id}
               className={`sym-carte ${finie ? "cliquable" : ""}`}
               data-testid="carte-tache" data-etat={t.etat}
               onClick={finie ? () => onAfficher(t) : undefined}
               role={finie ? "button" : undefined}
               tabIndex={finie ? 0 : undefined}
               onKeyDown={finie ? (e) => { if (e.key === "Enter") onAfficher(t) } : undefined}>
            {close && (
              <button className="sym-croix" aria-label="Fermer cette carte"
                      onClick={(e) => { e.stopPropagation(); onFermer(t) }}>×</button>
            )}
            <div className="sym-carte-q">{t.question}</div>
            {t.etat === "en_cours" && (
              <>
                {/* Le meme texte vivant que la banniere du chat : on suit une
                    tache de la file exactement comme la tache principale. */}
                <div className="sym-carte-etat">{t.activite || "en file d'attente"}</div>
                <div className="sym-piste" aria-label="Tâche en cours"><i /></div>
                {/* L'ARRÊT VIT SUR LA CARTE, là où la tâche est visible. Une
                    tâche de fond n'a pas de barre de saisie : sans ce bouton,
                    la seule issue était d'attendre. */}
                {onArreter && (
                  <button className="sym-carte-stop" data-testid="arreter-tache"
                          aria-label="Arrêter cette tâche"
                          onClick={(e) => { e.stopPropagation(); onArreter(t) }}>
                    Arrêter
                  </button>
                )}
              </>
            )}
            {t.etat === "attente_validation" && (
              <div className="sym-carte-etat">en attente de votre accord ci-dessus</div>
            )}
            {finie && (
              // Le texte vient du backend, pas d'un libelle fige : une tache
              // REFUSEE porte « refusée — rien n'a été fait ». Annoncer
              // « Terminée » dans ce cas ferait passer un refus pour un succes.
              <div className="sym-carte-etat ok">
                {(t.activite && t.activite !== "terminée" ? `${t.activite}, ` : "")
                 + "cliquez pour afficher le résultat"}
              </div>
            )}
            {(t.etat === "echec" || t.etat === "interrompue") && (
              <div className="sym-carte-etat ko">
                {ETAT_LIBELLE[t.etat]}{t.erreur ? ` : ${t.erreur}` : ""}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

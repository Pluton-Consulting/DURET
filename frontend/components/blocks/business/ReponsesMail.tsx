"use client"

/**
 * REPONSES PROPOSÉES À PLUSIEURS MAILS — des cartes horizontales, ÉDITABLES,
 * validées en une fois.
 *
 * Demandé par Noa le 31/08 (« cartes horizontales avec bouton pour valider
 * chacune, validées tout en une fois »), puis le même soir : « améliore le
 * design et rends-les éditables pour faciliter l'envoi ». Chaque carte porte
 * le mail (expéditeur, objet), la réponse proposée dans un CHAMP MODIFIABLE —
 * ce que la personne corrige est ce qui part — et une case. Le bouton unique
 * envoie DANS LE CHAT la demande d'envoi des réponses cochées, dans leur
 * dernière version (même canal que les pastilles de suggestion, `onAction`).
 * Ce composant n'envoie donc RIEN lui-même : chaque envoi réel repasse par
 * `envoyer_email` et sa validation (effet externe), la règle du projet ne
 * bouge pas.
 *
 * Le style vient des jetons de la charte (`--marque-*`), comme partout : le
 * champ est « creusé » dans la carte à la manière de la barre de saisie, la
 * carte cochée porte la couleur de la marque, une réponse retouchée le dit.
 */
import { useMemo, useState } from "react"

type Reponse = { ref?: string; de?: string; objet?: string; reponse?: string
  // La SYNTHÈSE du mail REÇU (ce qu'il demande) : le contexte qui permet de
  // juger la réponse sans rouvrir le message. 31/08, demande de Noa.
  synthese?: string; resume?: string }

type Props = {
  reponses: Reponse[]
  onAction?: (message: string) => void
}

function initiale(de?: string): string {
  const m = (de || "").trim()
  return (m.replace(/[<>"']/g, "").trim()[0] || "@").toUpperCase()
}

export function ReponsesMail({ reponses, onAction }: Props) {
  const valides = useMemo(() => (reponses || []).filter((r) => r && (r.reponse || "").trim()), [reponses])
  const [choisies, setChoisies] = useState<boolean[]>(() => valides.map(() => true))
  const [textes, setTextes] = useState<string[]>(() => valides.map((r) => (r.reponse || "").trim()))
  const [transmis, setTransmis] = useState(false)
  const n = choisies.filter(Boolean).length
  const toutes = n === valides.length

  if (!valides.length) return null

  const basculer = (i: number) =>
    !transmis && setChoisies((c) => c.map((v, j) => (j === i ? !v : v)))

  const corriger = (i: number, v: string) =>
    setTextes((t) => t.map((x, j) => (j === i ? v : x)))

  const envoyer = () => {
    if (!onAction || !n || transmis) return
    const lignes = valides
      .map((r, i) => ({ r, i }))
      .filter(({ i }) => choisies[i] && textes[i].trim())
      .map(({ r, i }) =>
        `- à ${r.de || "(expéditeur du message)"} — « ${r.objet || "sans objet"} »` +
        (r.ref ? ` (ref ${r.ref})` : "") + ` :\n${textes[i].trim()}`)
    if (!lignes.length) return
    onAction(
      `Envoie ces ${lignes.length} réponse(s) aux mails correspondants, telles quelles :\n${lignes.join("\n\n")}`)
    setTransmis(true)
  }

  return (
    <div className="sym-rm">
      <style>{`
        .sym-rm{ display:grid; gap:10px; }
        .sym-rm-rail{ display:flex; gap:12px; overflow-x:auto; padding:2px 2px 6px; scroll-snap-type:x proximity; }
        .sym-rm-carte{ flex:0 0 300px; scroll-snap-align:start; display:flex; flex-direction:column; gap:8px;
          border:1px solid var(--marque-border); border-radius:14px; padding:12px;
          background:var(--marque-surface); transition:border-color .18s ease, box-shadow .18s ease, opacity .18s ease; }
        .sym-rm-carte[data-choisie="true"]{ border-color:var(--marque-primary-mid);
          box-shadow:0 1px 2px rgb(0 0 0 / .04), 0 6px 18px -12px rgb(0 0 0 / .25); }
        .sym-rm-carte[data-eteinte="true"]{ opacity:.45; }
        .sym-rm-tete{ display:flex; align-items:center; gap:8px; cursor:pointer; }
        .sym-rm-tete input{ accent-color:var(--marque-primary); width:15px; height:15px; flex-shrink:0; }
        .sym-rm-avatar{ width:26px; height:26px; border-radius:50%; flex-shrink:0;
          display:flex; align-items:center; justify-content:center; font-size:12px; font-weight:700;
          background:var(--marque-primary-subtle); color:var(--marque-primary); }
        .sym-rm-qui{ min-width:0; display:grid; }
        .sym-rm-de{ font-size:11.5px; color:var(--marque-text-muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        .sym-rm-objet{ font-size:13px; font-weight:600; color:var(--marque-text-primary);
          overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        /* Le champ est CREUSÉ dans la carte, comme la barre de saisie : on voit
           d'un coup d'œil que c'est un texte à soi, qu'on peut corriger. */
        .sym-rm-contexte{ font-size:12px; line-height:1.45; color:var(--marque-text-muted);
          border-left:2px solid var(--marque-primary-light); padding:1px 0 1px 8px;
          max-height:72px; overflow-y:auto; }
        .sym-rm-texte{ width:100%; min-height:110px; max-height:220px; resize:vertical;
          border:1px solid transparent; border-radius:10px; padding:8px 10px;
          background:var(--marque-chat-champ, var(--marque-primary-subtle));
          font:inherit; font-size:13px; line-height:1.45; color:var(--marque-text-primary); }
        .sym-rm-texte:focus{ outline:none; border-color:var(--marque-primary-light); background:var(--marque-surface); }
        .sym-rm-texte:disabled{ opacity:.7; resize:none; }
        .sym-rm-pied{ display:flex; align-items:center; justify-content:space-between; min-height:16px;
          font-size:11px; color:var(--marque-text-muted); }
        .sym-rm-modifiee{ color:var(--marque-primary-mid); font-weight:600; }
        .sym-rm-actions{ display:flex; align-items:center; gap:12px; flex-wrap:wrap; }
        .sym-rm-envoyer{ border:1px solid var(--marque-primary); border-radius:999px; padding:7px 16px;
          font-size:13px; font-weight:600; cursor:pointer;
          background:var(--marque-primary); color:var(--marque-text-on-dark, #fff); transition:opacity .15s ease; }
        .sym-rm-envoyer:disabled{ opacity:.45; cursor:default; }
        .sym-rm-envoyer[data-transmis="true"]{ background:transparent; color:var(--marque-primary); }
        .sym-rm-tout{ border:none; background:none; padding:0; font-size:12px; cursor:pointer;
          color:var(--marque-primary-mid); text-decoration:underline; }
        .sym-rm-note{ font-size:12px; color:var(--marque-text-muted); }
      `}</style>

      <div className="sym-rm-rail">
        {valides.map((r, i) => {
          const modifiee = textes[i].trim() !== (r.reponse || "").trim()
          return (
            <div key={r.ref || i} className="sym-rm-carte"
                 data-choisie={String(!!choisies[i])} data-eteinte={String(transmis && !choisies[i])}>
              <label className="sym-rm-tete">
                <input type="checkbox" checked={!!choisies[i]} disabled={transmis}
                       onChange={() => basculer(i)}
                       aria-label={`Retenir la réponse à ${r.de || "ce message"}`} />
                <span className="sym-rm-avatar" aria-hidden="true">{initiale(r.de)}</span>
                <span className="sym-rm-qui">
                  <span className="sym-rm-de">{r.de || "(expéditeur inconnu)"}</span>
                  <span className="sym-rm-objet">{r.objet || "(sans objet)"}</span>
                </span>
              </label>
              {/* Le mail REÇU, en une ou deux phrases : on juge la réponse avec
                  son contexte sous les yeux, sans rouvrir le message. */}
              {(r.synthese || r.resume) && (
                <div className="sym-rm-contexte">{(r.synthese || r.resume || "").trim()}</div>
              )}
              {/* ÉDITABLE : ce que la personne corrige ici est EXACTEMENT ce qui
                  partira dans la demande d'envoi — pas la proposition d'origine. */}
              <textarea
                className="sym-rm-texte"
                value={textes[i]}
                disabled={transmis}
                onChange={(e) => corriger(i, e.target.value)}
                aria-label={`Réponse proposée à ${r.de || "ce message"} — modifiable`}
              />
              <div className="sym-rm-pied">
                <span>{textes[i].trim().length} caractère(s)</span>
                {modifiee && <span className="sym-rm-modifiee">modifiée</span>}
              </div>
            </div>
          )
        })}
      </div>

      <div className="sym-rm-actions">
        <button type="button" className="sym-rm-envoyer" data-transmis={String(transmis)}
                onClick={envoyer} disabled={!onAction || !n || transmis}>
          {transmis
            ? "Demande transmise — chaque envoi vous sera soumis"
            : `Envoyer ${n ? `les ${n} réponse(s) cochée(s)` : "(aucune réponse cochée)"}`}
        </button>
        {!transmis && valides.length > 1 && (
          <button type="button" className="sym-rm-tout"
                  onClick={() => setChoisies(valides.map(() => !toutes))}>
            {toutes ? "Tout décocher" : "Tout cocher"}
          </button>
        )}
        {!transmis && (
          <span className="sym-rm-note">
            Corrigez librement chaque réponse : c'est votre version qui part. Rien ne part sans votre accord.
          </span>
        )}
      </div>
    </div>
  )
}

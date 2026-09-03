"use client"

/**
 * REPONSES PROPOSÉES À PLUSIEURS MAILS — des cartes ÉDITABLES, validées en
 * une fois, PAGE PAR PAGE.
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
 * PAGE PAR PAGE, ET PLUS EN RAIL (03/09, relevé de Noa : « au lieu de plein
 * de petites cartes, en afficher une, deux ou trois, et un bouton flèche
 * gauche / flèche droite pour passer aux suivantes — là c'est trop petit et
 * pas pratique »). Les cartes prennent TOUTE la largeur disponible — une,
 * deux ou trois selon ce que mesure le conteneur — et deux flèches font
 * tourner les pages. Ce qui est coché ou corrigé sur une page RESTE coché ou
 * corrigé quand on change de page : l'état est global, la page n'est qu'une
 * fenêtre. Le même soir : « fais des cartes un peu plus grandes et améliore
 * leur design » — les seuils montent (une carte a besoin de 380 px pour
 * qu'un mail se lise), le champ de réponse passe à 200 px, l'objet se lit sur
 * deux lignes, et l'en-tête dit à qui l'on écrit avant ce qu'on lui écrit.
 *
 * LA QUANTITÉ. Un tableau de 95 clients donne 95 cartes dans UN bloc (le
 * skill ne pagine plus) ; seules celles de la page courante sont rendues, le
 * reste n'est que de la donnée. Mille cartes ne coûtent qu'une page à l'écran.
 *
 * Le style vient des jetons de la charte (`--marque-*`), comme partout.
 */
import { useEffect, useMemo, useRef, useState } from "react"

type Reponse = { ref?: string; de?: string; objet?: string; reponse?: string
  // La SYNTHÈSE du mail REÇU (ce qu'il demande) : le contexte qui permet de
  // juger la réponse sans rouvrir le message. 31/08, demande de Noa.
  synthese?: string; resume?: string
  // Un publipostage porte le NOM du destinataire (tiré du tableau) : on
  // l'affiche en tête, l'adresse dessous.
  nom?: string; prenom?: string }

type Props = { titre?: string;
  reponses: Reponse[]
  onAction?: (message: string) => void
}

function initiale(de?: string, nom?: string): string {
  const m = (nom || de || "").trim()
  return (m.replace(/[<>"']/g, "").trim()[0] || "@").toUpperCase()
}

/** Combien de cartes tiennent côte à côte, d'après la largeur RÉELLE du
 *  conteneur (et non celle de l'écran : le chat a une colonne à droite). Une
 *  carte a besoin d'environ 380 px pour qu'un mail se lise sans le plier. */
export function cartesParPage(largeur: number): number {
  if (largeur >= 1180) return 3
  if (largeur >= 760) return 2
  return 1
}

export function ReponsesMail({ titre, reponses, onAction }: Props) {
  const valides = useMemo(() => (reponses || []).filter((r) => r && (r.reponse || "").trim()), [reponses])
  const [choisies, setChoisies] = useState<boolean[]>(() => valides.map(() => true))
  const [textes, setTextes] = useState<string[]>(() => valides.map((r) => (r.reponse || "").trim()))
  const [transmis, setTransmis] = useState(false)
  const n = choisies.filter(Boolean).length
  const toutes = n === valides.length

  // ── LA PAGE ─────────────────────────────────────────────────────────────
  const conteneur = useRef<HTMLDivElement | null>(null)
  const [parPage, setParPage] = useState(1)
  const [page, setPage] = useState(0)
  useEffect(() => {
    const el = conteneur.current
    if (!el) return
    const mesurer = () => setParPage(cartesParPage(el.getBoundingClientRect().width))
    mesurer()
    // La colonne du chat change de largeur (panneau latéral, fenêtre
    // redimensionnée) : on suit, sinon trois cartes se tassent dans une
    // colonne devenue étroite.
    if (typeof ResizeObserver === "undefined") return
    const obs = new ResizeObserver(mesurer)
    obs.observe(el)
    return () => obs.disconnect()
  }, [])
  const pages = Math.max(1, Math.ceil(valides.length / parPage))
  // Un changement de largeur peut laisser la page courante au-delà de la fin.
  const pageSure = Math.min(page, pages - 1)
  const debut = pageSure * parPage
  const fin = Math.min(debut + parPage, valides.length)

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

  const Pages = pages > 1 ? (
    <div className="sym-rm-pages" data-testid="pages-reponses">
      <button type="button" className="sym-rm-fleche" aria-label="Cartes précédentes"
              disabled={pageSure === 0} onClick={() => setPage(Math.max(0, pageSure - 1))}>‹</button>
      <span>{debut + 1}–{fin} sur {valides.length}</span>
      <button type="button" className="sym-rm-fleche" aria-label="Cartes suivantes"
              disabled={pageSure >= pages - 1} onClick={() => setPage(Math.min(pages - 1, pageSure + 1))}>›</button>
    </div>
  ) : null

  return (
    <div className="sym-rm" ref={conteneur}>
      <style>{`
        .sym-rm{ display:grid; gap:12px; width:100%; }
        .sym-rm-tete-bloc{ display:flex; align-items:baseline; justify-content:space-between; gap:12px; flex-wrap:wrap; }
        .sym-rm-titre{ font-size:14px; font-weight:700; color:var(--marque-text-primary); }
        .sym-rm-compte{ font-size:12px; color:var(--marque-text-muted); }
        /* Les cartes de la page se PARTAGENT la largeur : une, deux ou trois
           colonnes égales, jamais un rail à faire défiler. */
        .sym-rm-page{ display:grid; gap:14px; grid-template-columns:repeat(var(--sym-rm-colonnes, 1), minmax(0, 1fr)); }
        .sym-rm-carte{ min-width:0; display:flex; flex-direction:column; gap:10px;
          border:1px solid var(--marque-border); border-radius:16px; padding:16px;
          background:var(--marque-surface);
          box-shadow:0 1px 2px rgb(0 0 0 / .04);
          transition:border-color .18s ease, box-shadow .18s ease, opacity .18s ease; }
        .sym-rm-carte[data-choisie="true"]{ border-color:var(--marque-primary-mid);
          box-shadow:0 1px 2px rgb(0 0 0 / .04), 0 10px 24px -14px rgb(0 0 0 / .28); }
        .sym-rm-carte[data-eteinte="true"]{ opacity:.45; }
        .sym-rm-tete{ display:flex; align-items:flex-start; gap:10px; cursor:pointer; }
        .sym-rm-tete input{ accent-color:var(--marque-primary); width:16px; height:16px; flex-shrink:0; margin-top:9px; }
        .sym-rm-avatar{ width:34px; height:34px; border-radius:50%; flex-shrink:0;
          display:flex; align-items:center; justify-content:center; font-size:14px; font-weight:700;
          background:var(--marque-primary-subtle); color:var(--marque-primary); }
        .sym-rm-qui{ min-width:0; display:grid; gap:2px; }
        /* À QUI d'abord, puis l'adresse : c'est le nom qu'on reconnaît. */
        .sym-rm-nom{ font-size:14px; font-weight:700; color:var(--marque-text-primary);
          overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        .sym-rm-de{ font-size:11.5px; color:var(--marque-text-muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        .sym-rm-objet{ font-size:13px; font-weight:600; color:var(--marque-text-primary); line-height:1.35;
          display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden;
          padding:8px 10px; border-radius:10px; background:var(--marque-canvas); }
        .sym-rm-etiquette{ font-size:10.5px; font-weight:700; text-transform:uppercase; letter-spacing:.07em;
          color:var(--marque-text-muted); margin-bottom:4px; }
        .sym-rm-contexte{ font-size:12.5px; line-height:1.5; color:var(--marque-text-muted);
          border-left:2px solid var(--marque-primary-light); padding:2px 0 2px 10px;
          max-height:96px; overflow-y:auto; }
        /* Le champ est CREUSÉ dans la carte, comme la barre de saisie : on voit
           d'un coup d'œil que c'est un texte à soi, qu'on peut corriger. */
        .sym-rm-texte{ width:100%; min-height:200px; max-height:420px; resize:vertical;
          border:1px solid transparent; border-radius:12px; padding:10px 12px;
          background:var(--marque-chat-champ, var(--marque-primary-subtle));
          font:inherit; font-size:13.5px; line-height:1.55; color:var(--marque-text-primary); }
        .sym-rm-texte:focus{ outline:none; border-color:var(--marque-primary-light); background:var(--marque-surface); }
        .sym-rm-texte:disabled{ opacity:.7; resize:none; }
        .sym-rm-pied{ display:flex; align-items:center; justify-content:space-between; min-height:16px;
          font-size:11px; color:var(--marque-text-muted); }
        .sym-rm-modifiee{ color:var(--marque-primary-mid); font-weight:600; }
        .sym-rm-manque{ color:var(--marque-error-text, #b3261e); font-weight:600; }
        /* La barre de pages : flèche, « 4–6 sur 30 », flèche. */
        .sym-rm-pages{ display:flex; align-items:center; justify-content:center; gap:12px;
          font-size:12.5px; color:var(--marque-text-muted); }
        .sym-rm-fleche{ width:34px; height:34px; border-radius:50%; border:1px solid var(--marque-border);
          background:var(--marque-surface); color:var(--marque-text-primary); cursor:pointer;
          display:inline-flex; align-items:center; justify-content:center; font-size:18px; line-height:1;
          transition:background .15s ease, opacity .15s ease; }
        .sym-rm-fleche:hover:not(:disabled){ background:var(--marque-primary-subtle); }
        .sym-rm-fleche:disabled{ opacity:.35; cursor:default; }
        .sym-rm-actions{ display:flex; align-items:center; gap:12px; flex-wrap:wrap; }
        .sym-rm-envoyer{ border:1px solid var(--marque-primary); border-radius:999px; padding:8px 18px;
          font-size:13px; font-weight:600; cursor:pointer;
          background:var(--marque-primary); color:var(--marque-text-on-dark, #fff); transition:opacity .15s ease; }
        .sym-rm-envoyer:disabled{ opacity:.45; cursor:default; }
        .sym-rm-envoyer[data-transmis="true"]{ background:transparent; color:var(--marque-primary); }
        .sym-rm-tout{ border:none; background:none; padding:0; font-size:12px; cursor:pointer;
          color:var(--marque-primary-mid); text-decoration:underline; }
        .sym-rm-note{ font-size:12px; color:var(--marque-text-muted); }
      `}</style>

      <div className="sym-rm-tete-bloc">
        {titre && <div className="sym-rm-titre">{titre}</div>}
        <div className="sym-rm-compte">
          {valides.length} carte{valides.length > 1 ? "s" : ""} · {n} cochée{n > 1 ? "s" : ""}
        </div>
      </div>

      <div className="sym-rm-page" style={{ ["--sym-rm-colonnes" as any]: parPage }}>
        {valides.slice(debut, fin).map((r, k) => {
          const i = debut + k
          const modifiee = textes[i].trim() !== (r.reponse || "").trim()
          // « [À COMPLÉTER] » : le tableau n'avait pas cette valeur pour cette
          // personne. On le SIGNALE sur la carte — c'est là qu'on corrige.
          const manque = textes[i].includes("[À COMPLÉTER]") || (r.objet || "").includes("[À COMPLÉTER]")
          const qui = [r.prenom, r.nom].filter(Boolean).join(" ")
          return (
            <div key={r.ref || i} className="sym-rm-carte"
                 data-choisie={String(!!choisies[i])} data-eteinte={String(transmis && !choisies[i])}>
              <label className="sym-rm-tete">
                <input type="checkbox" checked={!!choisies[i]} disabled={transmis}
                       onChange={() => basculer(i)}
                       aria-label={`Retenir la réponse à ${qui || r.de || "ce message"}`} />
                <span className="sym-rm-avatar" aria-hidden="true">{initiale(r.de, qui)}</span>
                <span className="sym-rm-qui">
                  <span className="sym-rm-nom">{qui || r.de || "(destinataire inconnu)"}</span>
                  {qui && <span className="sym-rm-de">{r.de || "(sans adresse)"}</span>}
                </span>
              </label>
              <div>
                <div className="sym-rm-etiquette">Objet</div>
                <div className="sym-rm-objet">{r.objet || "(sans objet)"}</div>
              </div>
              {/* Le mail REÇU, en une ou deux phrases : on juge la réponse avec
                  son contexte sous les yeux, sans rouvrir le message. */}
              {(r.synthese || r.resume) && (
                <div>
                  <div className="sym-rm-etiquette">Ce qu'il demande</div>
                  <div className="sym-rm-contexte">{(r.synthese || r.resume || "").trim()}</div>
                </div>
              )}
              <div>
                <div className="sym-rm-etiquette">Message — modifiable</div>
                {/* ÉDITABLE : ce que la personne corrige ici est EXACTEMENT ce qui
                    partira dans la demande d'envoi — pas la proposition d'origine. */}
                <textarea
                  className="sym-rm-texte"
                  value={textes[i]}
                  disabled={transmis}
                  onChange={(e) => corriger(i, e.target.value)}
                  aria-label={`Réponse proposée à ${qui || r.de || "ce message"} — modifiable`}
                />
              </div>
              <div className="sym-rm-pied">
                <span>{textes[i].trim().length} caractère(s)</span>
                {manque
                  ? <span className="sym-rm-manque">à compléter avant envoi</span>
                  : modifiee && <span className="sym-rm-modifiee">modifiée</span>}
              </div>
            </div>
          )
        })}
      </div>

      {Pages}

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

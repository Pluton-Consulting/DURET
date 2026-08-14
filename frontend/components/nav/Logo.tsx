/**
 * La marque Duret & Sols, en un seul endroit.
 *
 * Elle apparaissait deux fois, écrite à la main à chaque fois — barre de
 * navigation et écran de connexion. Deux copies d'un logo divergent au premier
 * ajustement, et la troisième page qui en aura besoin en fera une troisième.
 *
 * Le tracé est INLINE et non un <img src="/duret-sols.svg"> : la marque se pose
 * ainsi sans requête réseau, sans clignotement au chargement, et hérite de la
 * taille de son conteneur. Le fichier public/ reste pour les usages externes
 * (signature de mail, document, page hors application).
 */

/** Les trois carrés, seuls. Hauteur pilotée par `taille` (en pixels). */
export function MarqueDuret({ taille = 26 }: { taille?: number }) {
  return (
    <svg
      viewBox="0 0 1024 640"
      height={taille}
      width={taille * 1.6}
      fill="none"
      role="img"
      aria-label="Duret & Sols"
      style={{ display: "block", flexShrink: 0 }}
    >
      {/* Mesures relevées sur le logo fourni, pas estimées : côtés 0,282 /
          0,523 / 1 du carré bleu. Voir public/duret-sols.svg. */}
      <rect x="404" y="20" width="598" height="598" stroke="#0687DA" strokeWidth="40" />
      <rect x="20" y="314" width="294" height="292" stroke="#F41122" strokeWidth="40" />
      <rect x="172" y="68" width="144" height="142" stroke="#FFE202" strokeWidth="36" />
    </svg>
  )
}

/**
 * Marque + nom. `taille` est celle du texte ; les carrés se calent dessus.
 *
 * Le nom reste écrit à côté du symbole : trois carrés ne se lisent pas
 * « Duret & Sols » pour qui découvre l'outil, et une marque interne n'a pas la
 * notoriété qui permet de s'en passer.
 */
export default function Logo({ taille = 20 }: { taille?: number }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: taille * 0.5 }}>
      <MarqueDuret taille={taille * 1.15} />
      <span
        style={{
          fontSize: taille,
          fontWeight: 800,
          color: "var(--marque-text-primary)",
          letterSpacing: "-0.02em",
          whiteSpace: "nowrap",
          lineHeight: 1,
        }}
      >
        Duret <span style={{ color: "var(--marque-brand-blue)" }}>&amp; Sols</span>
      </span>
    </span>
  )
}

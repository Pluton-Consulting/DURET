import type { Metadata } from "next"
import { SessionProvider } from "next-auth/react"

export const metadata: Metadata = {
  title: "Duret & Sols",
  description: "Assistant IA interne Duret & Sols",
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fr">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap"
          rel="stylesheet"
        />
        <style dangerouslySetInnerHTML={{ __html: `
          /* ── Charte Duret & Sols ──────────────────────────────────────
             Tirée du logo : trois carrés évidés, bleu / rouge / jaune, sur
             noir. Les trois teintes sont relevées SUR l'image et non estimées
             (#0687DA, #F41122, #FFE202).

             Elles ne peuvent pas servir telles quelles partout. Mesuré :
             #0687DA ne donne que 3,83 de contraste avec du blanc — sous le
             seuil de 4,5 — et #FFE202 tombe à 1,30, donc illisible en texte
             quelle que soit la taille. On garde donc les teintes EXACTES pour
             la marque (--color-brand-*), et on en dérive des variantes
             assombries pour tout ce qui porte du texte. Le logo reste juste,
             l'interface reste lisible. */
            --color-brand-blue:     #0687DA;   /* le carré bleu, tel quel */
            --color-brand-red:      #F41122;   /* le carré rouge, tel quel */
            --color-brand-yellow:   #FFE202;   /* le carré jaune, tel quel */
            --color-brand-ink:      #0B0E11;   /* le fond noir du logo */

            --color-primary:        #0A6FB4;   /* blanc dessus : 5,32 */
            --color-primary-hover:  #0B5F9B;
            --color-primary-mid:    #0687DA;   /* la teinte de marque */
            --color-primary-light:  #9DD1F2;
            --color-primary-subtle: #E5F2FB;
            --color-leaf:           #0687DA;
            --color-canvas:         #F4F6F8;
            --color-surface:        #FFFFFF;
            --color-border:         #DFE4EA;
            --color-text-primary:   #0B0E11;   /* le noir du logo : 19,35 */
            --color-text-body:      #2E3742;   /* 12,06 */
            --color-text-muted:     #606B78;   /* 5,21 — lisible sur le canevas */
            --color-text-on-dark:   #FFFFFF;
            --color-on-dark-accent: #9DD1F2;
            --color-paid-bg:        #E5F2FB;
            --color-paid-text:      #0B66A6;   /* 6,06 */
            /* Le jaune de la marque, en fond seulement ; le texte au-dessus est
               un ambre profond, sans quoi rien ne se lit. */
            --color-pending-bg:     #FFF8CC;
            --color-pending-text:   #7A6B00;   /* 4,97 sur ce fond */
            --color-progress-bg:    #E5F2FB;
            --color-progress-text:  #0A6FB4;
            /* Idem pour le rouge : #F41122 plafonne à 4,24 avec du blanc. */
            --color-error-bg:       #FDE7E9;
            --color-error-text:     #CC0E1B;   /* 5,76 */
            --radius-card:          20px;
            --radius-card-sm:       14px;
            --radius-pill:          9999px;
            --radius-icon:          10px;
            /* Ombres teintées de l'encre du logo, pas d'un gris neutre : une
               ombre grise sous une interface bleue paraît sale. */
            --shadow-card:          0 2px 12px rgba(11,14,17,0.07);
            --shadow-hover:         0 4px 20px rgba(11,14,17,0.13);
            --shadow-card-hover:    0 4px 20px rgba(11,14,17,0.13);
            --font:                 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            --font-family:          'Inter', sans-serif;
          }
          *, *::before, *::after { box-sizing: border-box; }
          body {
            margin: 0;
            font-family: var(--font);
            color: var(--color-text-body);
            background: var(--color-canvas);
            -webkit-font-smoothing: antialiased;
          }
          a { color: inherit; text-decoration: none; }
          button, input, select, textarea { font-family: var(--font); }
          ::-webkit-scrollbar { width: 6px; height: 6px; }
          ::-webkit-scrollbar-track { background: transparent; }
          ::-webkit-scrollbar-thumb { background: var(--color-border); border-radius: 3px; }

          /* ── Animations & micro-interactions ── */
          @keyframes symFadeUp { from { opacity:0; transform:translateY(12px) } to { opacity:1; transform:translateY(0) } }
          @keyframes symFadeIn { from { opacity:0 } to { opacity:1 } }
          @keyframes symShimmer { 0%{background-position:-450px 0} 100%{background-position:450px 0} }
          @keyframes symFloat { 0%,100%{transform:translateY(0)} 50%{transform:translateY(-5px)} }
          @keyframes symPop { 0%{transform:scale(.94)} 60%{transform:scale(1.03)} 100%{transform:scale(1)} }
          .sym-in   { animation: symFadeUp .5s cubic-bezier(.22,.61,.36,1) both; }
          .sym-in-1 { animation-delay:.05s } .sym-in-2 { animation-delay:.11s }
          .sym-in-3 { animation-delay:.17s } .sym-in-4 { animation-delay:.23s }
          .sym-in-5 { animation-delay:.29s } .sym-in-6 { animation-delay:.35s }
          .sym-fade { animation: symFadeIn .45s ease both; }
          .sym-pop  { animation: symPop .35s cubic-bezier(.22,.61,.36,1) both; }
          .sym-card { transition: transform .25s cubic-bezier(.22,.61,.36,1), box-shadow .25s ease, border-color .25s ease; }
          .sym-card:hover { transform: translateY(-3px); box-shadow: var(--shadow-card-hover); }
          button, a, .sym-tap { transition: background-color .2s ease, color .2s ease, transform .12s ease, box-shadow .2s ease, border-color .2s ease; }
          .sym-tap:active { transform: scale(.97); }
          .sym-skeleton { background:linear-gradient(90deg, var(--color-border) 25%, var(--color-primary-subtle) 50%, var(--color-border) 75%);
            background-size:900px 100%; animation:symShimmer 1.3s infinite linear; border-radius:var(--radius-card-sm); }
          @media (prefers-reduced-motion: reduce){
            .sym-in,.sym-fade,.sym-pop,.sym-card,.sym-tap,.sym-skeleton{ animation:none!important; transition:none!important }
            .sym-card:hover{ transform:none }
          }
          /* ── Adaptation aux petits écrans ────────────────────────────
             TOUT est enfermé dans cette media query : au-dessus de 900px,
             aucune de ces règles n'existe, donc la version bureau est
             inchangée par construction. Le !important est nécessaire (et
             sans risque ici) parce que les pages posent leurs styles en
             ligne, qui l'emportent autrement sur une classe. */
          @media (max-width: 900px){
            /* Marges de page : 32px sur un écran de 390px, c'est un sixième
               de la largeur perdu de chaque côté. */
            .sym-page{ padding-left:16px!important; padding-right:16px!important;
                       padding-top:20px!important; padding-bottom:24px!important; }
            /* Grilles d'indicateurs : elles se REPLIENT au lieu de se
               comprimer. À 4, 5 ou 6 colonnes fixes, chaque carte tombait
               sous 70px et devenait illisible. */
            .sym-grid-auto{ grid-template-columns:repeat(auto-fit,minmax(150px,1fr))!important; }
            /* Grilles à deux colonnes de formulaire : une seule colonne. */
            .sym-grid-1{ grid-template-columns:1fr!important; }
            /* Blocs à largeur plancher : ils défilent au lieu de pousser
               la page entière hors de l'écran. */
            .sym-scroll-x{ overflow-x:auto!important; }
            /* Cartes à largeur figée (tableaux, graphiques) : elles suivent
               la largeur disponible. */
            .sym-fluide{ max-width:100%!important; }
            /* Bulles de conversation : 70% d'un petit écran ne laisse pas
               de place au texte. */
            .sym-bulle{ max-width:88%!important; }
          }
        ` }} />
      </head>
      <body>
        {/* refetch coupé : évite le repolling en boucle de /api/auth/session (jusqu'à 6 s
            quand le process compile) qui bloquait la navigation. La session reste valide via le JWT. */}
        <SessionProvider refetchOnWindowFocus={false} refetchInterval={0}>
          {children}
        </SessionProvider>
      </body>
    </html>
  )
}

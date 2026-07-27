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
          :root {
            --color-primary:        #1E3A5F;
            --color-primary-hover:  #16304F;
            --color-primary-mid:    #2E6BB0;
            --color-primary-light:  #AECBE8;
            --color-primary-subtle: #EAF1FA;
            --color-leaf:           #4A90D9;
            --color-canvas:         #F1F5FA;
            --color-surface:        #FFFFFF;
            --color-border:         #DCE4EE;
            --color-text-primary:   #16202E;
            --color-text-body:      #33424F;
            --color-text-muted:     #78899B;
            --color-text-on-dark:   #FFFFFF;
            --color-on-dark-accent: #AECBE8;
            --color-paid-bg:        #DDEBF7;
            --color-paid-text:      #1F5FA6;
            --color-pending-bg:     #FDF3E3;
            --color-pending-text:   #9A6520;
            --color-progress-bg:    #E4EDFB;
            --color-progress-text:  #2B5AA0;
            --color-error-bg:       #FEE2E2;
            --color-error-text:     #DC2626;
            --radius-card:          20px;
            --radius-card-sm:       14px;
            --radius-pill:          9999px;
            --radius-icon:          10px;
            --shadow-card:          0 2px 12px rgba(16,32,48,0.07);
            --shadow-hover:         0 4px 20px rgba(16,32,48,0.12);
            --shadow-card-hover:    0 4px 20px rgba(16,32,48,0.12);
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

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
            --shadow-card:          0 2px 12px rgba(16,32,48,0.07);
            --shadow-hover:         0 4px 20px rgba(16,32,48,0.12);
            --font:                 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
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

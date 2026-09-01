import type { Metadata, Viewport } from "next"
import { SessionProvider } from "next-auth/react"
import { TooltipProvider } from "@/components/ui/tooltip"

// LE STYLE VIT DANS DES FICHIERS CSS, PLUS DANS CE COMPOSANT.
//
// Il était injecté ici par `dangerouslySetInnerHTML` : praticable tant que
// tout tenait en styles inline, intenable dès lors que Tailwind, shadcn,
// AI Elements et Extend UI doivent lire les mêmes tokens. La chaîne est
// désormais explicite et à un seul sens :
//
//     charte.css  (les couleurs du client — LE SEUL fichier à changer)
//        ↓
//     theme.css   (la traduction vers Tailwind + shadcn — identique partout)
//        ↓
//     les composants
import "./theme.css"
// APRÈS `theme.css`, et c'est tout l'objet : le palier téléphone doit
// pouvoir corriger le palier 900 px, qui vit en fin de theme.css. Importé
// depuis theme.css (un `@import` se place en tête), il passait AVANT et se
// faisait écraser — la moitié de ce fichier ne s'appliquait jamais.
import "./mobile.css"

export const metadata: Metadata = {
  title: "Duret & Sols",
  description: "Assistant IA interne Duret & Sols",
}

// `viewportFit: "cover"` : sans lui, `env(safe-area-inset-*)` vaut zéro et
// l'en-tête passe sous l'encoche des iPhone.
//
// LE ZOOM EST BLOQUÉ — décision de Noa (01/09) : « tu dois bloquer les pages en
// version mobile pour éviter qu'elles se zooment et se dézooment toutes seules ».
//
// Ce commentaire disait le contraire, et l'argument n'était pas faux : brider le
// zoom est une gêne d'accessibilité, et le zoom intempestif d'iOS se règle EN
// PRINCIPE par la taille des champs. Mais en principe seulement — il suffit d'un
// champ à 13 px oublié quelque part, ou d'un bloc qui déborde de quelques pixels,
// pour que l'écran parte tout seul et n'y revienne pas. Sur un outil interne
// consulté au téléphone sur un chantier, une page qui bouge sous le doigt coûte
// plus que le zoom qu'on retire.
//
// LES DEUX PARADES SONT POSÉES, pas une seule : les champs sont ramenés à 16 px
// dans `mobile.css`, ET le zoom est bridé ici. Si l'accessibilité redevient
// prioritaire, retirer les deux lignes ci-dessous suffit — les champs, eux,
// resteront corrects.
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  viewportFit: "cover",
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
      </head>
      <body>
        {/* refetch coupé : évite le repolling en boucle de /api/auth/session (jusqu'à 6 s
            quand le process compile) qui bloquait la navigation. La session reste valide via le JWT. */}
        <SessionProvider refetchOnWindowFocus={false} refetchInterval={0}>
          {/* SANS CE FOURNISSEUR, UNE INFO-BULLE FAIT PLANTER LA PAGE.
              Notre `Tooltip` est la primitive Radix nue : elle exige un
              ancêtre `TooltipProvider`, sinon elle lève une erreur au
              montage. Or la plupart des composants AI Elements en posent une
              (les actions d'un artefact, la navigation d'un aperçu web, tout
              `PromptInputButton` avec `tooltip`). Le poser ici une fois rend
              la bibliothèque entière utilisable sans piège : le jour où on
              câble un de ces composants, il marche, au lieu de casser
              l'écran à sa première apparition. */}
          <TooltipProvider delayDuration={300}>
            {children}
          </TooltipProvider>
        </SessionProvider>
      </body>
    </html>
  )
}

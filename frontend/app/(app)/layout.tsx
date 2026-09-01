import { auth } from "@/lib/auth"
import { redirect } from "next/navigation"
import EnTete from "@/components/nav/EnTete"
import Corps from "@/components/nav/Corps"

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const session = await auth()
  if (!session) redirect("/login")

  const user = (session as any).user
  const role: string = user?.role || "terrain"
  const email: string = user?.email || ""
  const name: string = user?.name || email.split("@")[0]

  return (
    // `100dvh` et non `100vh` : sur téléphone, `vh` compte la hauteur écran
    // BARRE D'ADRESSE MASQUÉE, donc le document dépasse toujours de quelques
    // dizaines de pixels et la page rebondit sous le doigt. `dvh` suit la
    // hauteur réellement visible. Le repli `100vh` reste pour les navigateurs
    // qui ne connaissent pas l'unité.
    <div style={{ minHeight: "100vh", background: "var(--marque-canvas)" }}
         className="sym-hauteur-ecran">
      <EnTete role={role} email={email} name={name} />
      <Corps>{children}</Corps>
    </div>
  )
}

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
    <div style={{ minHeight: "100vh", background: "var(--marque-canvas)" }}>
      <EnTete role={role} email={email} name={name} />
      <Corps>{children}</Corps>
    </div>
  )
}

import { auth } from "@/lib/auth"
import { redirect } from "next/navigation"
import TopNav from "@/components/nav/TopNav"

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const session = await auth()
  if (!session) redirect("/login")

  const user = (session as any).user
  const role: string = user?.role || "terrain"
  const email: string = user?.email || ""
  const name: string = user?.name || email.split("@")[0]

  return (
    <div style={{ minHeight: "100vh", background: "var(--color-canvas)" }}>
      <TopNav role={role} email={email} name={name} />
      <main className="sym-fade" style={{ paddingTop: 64, minHeight: "calc(100vh - 64px)" }}>
        {children}
      </main>
    </div>
  )
}

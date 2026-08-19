import { redirect } from "next/navigation"
// Cet onglet a fusionné dans « Connaissances » (interface v2) : on y emmène.
export default function Ancien() { redirect("/connaissances") }

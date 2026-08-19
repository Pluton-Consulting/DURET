import { redirect } from "next/navigation"
// Les onglets par agent ont disparu (interface v2) : leurs indicateurs vivent
// dans le tableau de bord, une carte par expert.
export default function Ancien() { redirect("/accueil") }

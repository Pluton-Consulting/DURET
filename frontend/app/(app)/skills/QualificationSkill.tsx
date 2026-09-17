"use client"
import { useEffect, useState } from "react"
export default function QualificationSkill({ name, apiUrl, token }: { name: string; apiUrl: string; token: string }) {
  const [cas, setCas] = useState("[]")
  const [message, setMessage] = useState("")
  const [busy, setBusy] = useState(false)
  const [versions, setVersions] = useState<{version:number; description:string}[]>([])
  useEffect(() => {
    let actif = true
    const headers = { Authorization: `Bearer ${token}` }
    Promise.all([fetch(`${apiUrl}/api/skills/${encodeURIComponent(name)}/qualifications`, {headers}), fetch(`${apiUrl}/api/skills/${encodeURIComponent(name)}/versions`, {headers})])
      .then(async ([a,b]) => {
        if (!a.ok || !b.ok) throw new Error("Historique indisponible")
        const [e,v] = await Promise.all([a.json(),b.json()])
        if (actif) { setCas(JSON.stringify(e[0]?.cas || [],null,2)); setVersions(v) }
      }).catch(() => { if (actif) setMessage("Historique des tests indisponible") })
    return () => { actif = false }
  }, [name,apiUrl,token])
  async function lancer(path:string,body:unknown) {
    setBusy(true); setMessage("")
    try {
      const r = await fetch(`${apiUrl}/api/skills/${encodeURIComponent(name)}${path}`, { method:"POST", headers:{Authorization:`Bearer ${token}`,"Content-Type":"application/json"},body:JSON.stringify(body) })
      const j = await r.json()
      if (!r.ok) throw new Error(j.detail || "Échec")
      setMessage(j.message || (j.passed ? "Tous les cas ont réussi dans l’exécuteur isolé. Relisez-les avant de valider." : "Qualification non réussie : " + (j.error || "au moins un cas est en échec")))
    } catch(e) { setMessage(e instanceof Error ? e.message : "Échec") }
    finally { setBusy(false) }
  }
  return <details style={{marginTop:12}}><summary>Qualification et versions</summary>
    <p>Au moins trois cas fictifs distincts, avec une entrée « data » et un résultat « attendu ». Inclure un cas limite. Aucune donnée client dans les tests.</p>
    <textarea aria-label="Cas de qualification JSON" value={cas} onChange={e=>setCas(e.target.value)} rows={7} style={{width:"100%",fontFamily:"monospace"}} />
    <button disabled={busy} onClick={()=>{try { void lancer("/qualifier",{cas:JSON.parse(cas)}) } catch { setMessage("JSON invalide") }}}>Tester les cas dans l’exécuteur isolé</button>
    <p role="status">{message}</p>
    {versions.map(v=><p key={v.version}>Version {v.version} <button disabled={busy} onClick={()=>void lancer(`/restaurer-version/${v.version}`,{})}>Restaurer en brouillon</button></p>)}
  </details>
}

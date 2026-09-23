"use client"
import { useState, useEffect, Fragment } from "react"
import { signIn, useSession } from "next-auth/react"
import { ROLE_LABELS, ROLE_COLORS, nomExpert } from "@/lib/permissions"
import ImportTab from "@/components/settings/ImportTab"
import SyncTab from "@/components/settings/SyncTab"
import NiveauxNas from "@/components/settings/NiveauxNas"
import TriNas from "@/components/settings/TriNas"
import ClesApiTab from "@/components/settings/ClesApiTab"
import MonCode from "@/components/settings/MonCode"

type SubTab = "code" | "utilisateurs" | "plages" | "rbac" | "agents" | "quotas" | "services" | "import" | "synchro" | "cles"
type Role = "super_admin" | "direction" | "commercial" | "bureau_etudes" | "conducteur" | "administratif" | "terrain"
type Agent = "agent1" | "agent2" | "agent3"

interface AgentPermissions { agent1: boolean; agent2: boolean; agent3: boolean }
interface User {
  id: string; email: string; name: string | null; role: Role
  actif: boolean; created_at: string; agent_permissions: AgentPermissions
  // Les dossiers de la boîte partagée ouverts à ce compte, en plus de la
  // réception (11/09). null = aucune restriction ; [] = la réception seule.
  dossiers_mail?: string[] | null
  // La carte de connexion de ce profil est-elle protégée par un code (13/09) ?
  a_code?: boolean
  // Le code lui-même (14/09, migration 042), pour les profils qu'on gère.
  // null avec a_code : posé avant la 042, illisible — un nouveau le remplace.
  code?: string | null
}
interface DossierBoite { nom: string; libelle: string }
const ROLES_ADMIN: Role[] = ["super_admin", "direction"]

/** « Tous les dossiers », « Réception seule », « Réception + 2 dossiers ». */
function resumeDossiers(d: string[] | null | undefined, role: Role): string {
  if (ROLES_ADMIN.includes(role) || d == null) return "Tous les dossiers"
  if (d.length === 0) return "Réception seule"
  return `Réception + ${d.length} dossier${d.length > 1 ? "s" : ""}`
}
interface Props {
  initialUsers: User[]; backendToken: string; currentRole: string; apiUrl: string
}

const METIER_ROLES: Role[] = ["commercial", "bureau_etudes", "conducteur", "administratif", "terrain"]
const CREATABLE: Record<string, Role[]> = {
  super_admin: ["direction", ...METIER_ROLES],
  direction: METIER_ROLES,
}

function canTogglePerm(mgr: string, _agent: Agent, target: Role): boolean {
  if (mgr === "super_admin") return true
  if (mgr === "direction") return target !== "super_admin"
  return false
}

// Paramètres est désormais ouvert à TOUS les rôles — pour la connexion Google
// personnelle. Les onglets d'administration, eux, gardent leurs rôles : les
// quatre premiers, jadis sans restriction, ne l'étaient que parce que la PAGE
// filtrait à l'entrée (super_admin/direction) — la restriction descend ici.
const ALL_SUB_TABS: { key: SubTab; label: string; roles?: string[]; permission?: string }[] = [
  // (15/09, Duret, demande de Noa) « CHAQUE PERSONNE DOIT POUVOIR CHANGER SON
  // PROPRE MOT DE PASSE » : l'onglet du code est à tous les rôles, administrateur
  // compris — c'est son code qui ouvre le bouton « Admin » depuis que le lien
  // magique est coupé. L'onglet « Mon compte Google » est retiré : la boîte de
  // l'entreprise passe par un mot de passe d'application, il ne servait plus.
  { key: "code", label: "Mon code de connexion" },
  // L'onglet « Mes appareils » a existé une journée (03/09) puis a été retiré
  // à la demande de Noa (« inutile ») : « Se déconnecter » ferme l'appareil
  // courant, et les routes /api/auth/appareils restent pour l'administration.
  { key: "utilisateurs", label: "Utilisateurs", roles: ["super_admin", "direction"] },
  { key: "plages", label: "Plages horaires", roles: ["super_admin", "direction"] },
  { key: "rbac", label: "Permissions", roles: ["super_admin", "direction"] },
  // 01/09 (Noa) : « États des agents » rejoint l'administration système.
  { key: "agents", label: "États des agents", roles: ["super_admin"] },
  { key: "quotas", label: "Quotas", roles: ["super_admin"] },
  { key: "services", label: "Services connectés", roles: ["super_admin"] },
  // (14/09) S'ouvre aussi à tout rôle qui a reçu « Importer des fichiers » dans Permissions.
  { key: "import", label: "Import de données", roles: ["super_admin", "direction"], permission: "import_documents" },
  // Déclencher une synchronisation touche à toutes les sources de
  // l'entreprise : réservé à l'administration système, comme l'endpoint.
  { key: "synchro", label: "Synchronisations", roles: ["super_admin"] },
  // Les clés commandent quels modèles répondent : administration système.
  { key: "cles", label: "Clés API", roles: ["super_admin"] },
]

/** Les dossiers de la boîte rangés en ARBRE, d'après leur chemin (« Clients/Martin/Devis »). */
interface NoeudDossier { cle: string; libelle: string; dossier: DossierBoite | null; enfants: NoeudDossier[] }

export function arbreDossiers(dossiers: DossierBoite[]): NoeudDossier[] {
  const racines: NoeudDossier[] = []
  const parCle = new Map<string, NoeudDossier>()
  // Le préfixe système de Gmail n'est pas un niveau que l'on choisit.
  const chemin = (d: DossierBoite) => (d.nom.startsWith("[Gmail]/") ? d.nom.slice(8) : d.nom).split("/").filter(Boolean)
  const tries = [...dossiers].sort((a, b) => chemin(a).length - chemin(b).length || a.libelle.localeCompare(b.libelle, "fr"))
  for (const d of tries) {
    const segments = chemin(d)
    let niveau = racines
    let cle = ""
    segments.forEach((seg, i) => {
      cle = cle ? `${cle}/${seg}` : seg
      let noeud = parCle.get(cle)
      if (!noeud) {
        noeud = { cle, libelle: i === segments.length - 1 ? (segments.length > 1 ? seg : d.libelle) : seg, dossier: null, enfants: [] }
        parCle.set(cle, noeud)
        niveau.push(noeud)
      }
      if (i === segments.length - 1) noeud.dossier = d
      niveau = noeud.enfants
    })
  }
  const trier = (liste: NoeudDossier[]) => {
    liste.sort((a, b) => a.libelle.localeCompare(b.libelle, "fr"))
    liste.forEach((n) => trier(n.enfants))
  }
  trier(racines)
  // Les envoyés restent en tête, comme le serveur les propose.
  racines.sort((a, b) => Number(b.dossier?.nom === "envoyes") - Number(a.dossier?.nom === "envoyes"))
  return racines
}

/** Tous les dossiers réels sous un nœud (lui compris). */
function nomsSous(n: NoeudDossier): string[] {
  return [...(n.dossier ? [n.dossier.nom] : []), ...n.enfants.flatMap(nomsSous)]
}

/** Les cases des dossiers de la boîte. La réception n'y est pas : toujours ouverte.
 *
 * EN CASCADE (15/09, Duret, demande de Noa : « quand il y en a beaucoup c'est
 * horrible »). Seuls les dossiers de premier degré s'affichent ; cocher un
 * dossier montre ses sous-dossiers, et ainsi de suite. Décocher un dossier
 * décoche aussi ce qu'il contient : un choix qu'on ne voit plus ne doit pas
 * rester actif en douce. Un niveau qui n'existe pas comme dossier dans la
 * boîte (« Clients » quand seul « Clients/Martin » existe) s'affiche en simple
 * titre, ouvert. Rien ne change côté serveur : un dossier coché ouvre CE
 * dossier, pas ses sous-dossiers.
 */
function CasesDossiers({ dossiers, choix, onChange }: {
  dossiers: DossierBoite[]; choix: string[]; onChange: (choix: string[]) => void
}) {
  const arbre = arbreDossiers(dossiers)
  const basculer = (n: NoeudDossier, coche: boolean) => {
    if (!n.dossier) return
    if (coche) onChange(choix.includes(n.dossier.nom) ? choix : [...choix, n.dossier.nom])
    else { const retires = new Set(nomsSous(n)); onChange(choix.filter((x) => !retires.has(x))) }
  }
  const rendre = (liste: NoeudDossier[], degre: number): React.ReactNode => (
    <div style={{ display: "flex", flexDirection: "column", gap: 4, marginLeft: degre ? 22 : 0,
                  paddingLeft: degre ? 10 : 0, borderLeft: degre ? "2px solid var(--marque-border)" : "none" }}>
      {liste.map((n) => {
        const coche = !!n.dossier && choix.includes(n.dossier.nom)
        const ouvert = !n.dossier || coche
        const cochesDessous = nomsSous(n).filter((x) => x !== n.dossier?.nom && choix.includes(x)).length
        return (
          <div key={n.cle}>
            {n.dossier ? (
              <label className="sym-tap" style={{
                display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13, cursor: "pointer",
                padding: "5px 12px", borderRadius: "var(--marque-radius-pill)",
                border: coche ? "1px solid var(--marque-primary)" : "1px solid var(--marque-border)",
                background: coche ? "var(--marque-surface)" : "transparent", color: "var(--marque-text-body)",
              }}>
                <input type="checkbox" checked={coche} onChange={(e) => basculer(n, e.target.checked)} />
                {n.libelle}
                {n.enfants.length > 0 && (
                  <span style={{ fontSize: 11, color: "var(--marque-text-muted)" }}>
                    {coche ? "▾" : "▸"} {n.enfants.length} sous-dossier{n.enfants.length > 1 ? "s" : ""}
                    {cochesDessous ? ` · ${cochesDessous} coché${cochesDessous > 1 ? "s" : ""}` : ""}
                  </span>
                )}
              </label>
            ) : (
              <div style={{ fontSize: 12, fontWeight: 600, color: "var(--marque-text-muted)", padding: "4px 2px" }}>{n.libelle}</div>
            )}
            {ouvert && n.enfants.length > 0 && <div style={{ marginTop: 4 }}>{rendre(n.enfants, degre + 1)}</div>}
          </div>
        )
      })}
    </div>
  )
  return <div data-testid="cases-dossiers" style={{ maxHeight: 360, overflowY: "auto", paddingRight: 4 }}>{rendre(arbre, 0)}</div>
}

/* ---------- USERS TAB ---------- */
function UsersTab({ initialUsers, backendToken, currentRole, apiUrl }: Props) {
  const [users, setUsers] = useState<User[]>(initialUsers)
  const [form, setForm] = useState({ email: "", name: "", role: "terrain" as Role, dossiers: [] as string[], code: "" })
  // LES DOSSIERS DE LA BOÎTE PARTAGÉE (11/09, Duret) : lus sur la boîte elle-
  // même. Vide avec une raison quand aucune boîte d'entreprise n'est reliée —
  // les cases n'ont alors pas de sens, et rien n'est restreint.
  const [dossiersBoite, setDossiersBoite] = useState<DossierBoite[]>([])
  const [dossiersErreur, setDossiersErreur] = useState("")
  const [editDossiers, setEditDossiers] = useState<{ id: string; nom: string; libres: boolean; choix: string[] } | null>(null)
  const [dossiersEnCours, setDossiersEnCours] = useState(false)
  // L'ADRESSE DE LA BOÎTE DE L'ENTREPRISE (13/09) : un profil créé dessus
  // apparaît en carte sur la page de connexion, sans lien magique. Elle est
  // posée d'office dans le formulaire ; un administrateur garde la sienne.
  const [adresseBoite, setAdresseBoite] = useState("")
  useEffect(() => {
    fetch(`${apiUrl}/api/users/dossiers-mail`, { headers: { Authorization: `Bearer ${backendToken}` }, cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((j) => { setDossiersBoite(j.dossiers || []); setDossiersErreur(j.erreur || ""); setAdresseBoite(j.adresse || "") })
      .catch((e) => setDossiersErreur(e?.message || "dossiers indisponibles"))
  }, [apiUrl, backendToken])
  const boiteReliee = dossiersBoite.length > 0
  // Une adresse déjà portée par un compte : le nouveau sera un PROFIL de plus
  // sur cette boîte, et son prénom devient obligatoire (c'est la carte).
  const adresseDejaPortee = form.email.trim() !== "" &&
    users.some((u) => u.email.toLowerCase() === form.email.trim().toLowerCase())
  const surLaBoite = adresseBoite !== "" && form.email.trim().toLowerCase() === adresseBoite.toLowerCase()
  // Chaque profil a sa carte sur la page de connexion (14/09) : son nom est
  // ce qui s'y affiche. Seul le super_admin, qui n'a jamais de carte, s'en passe.
  const prenomRequis = adresseDejaPortee || surLaBoite || form.role !== "super_admin"

  async function enregistrerDossiers() {
    if (!editDossiers) return
    setDossiersEnCours(true)
    try {
      const res = await fetch(`${apiUrl}/api/users/${editDossiers.id}/dossiers-mail`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${backendToken}` },
        body: JSON.stringify({ dossiers: editDossiers.libres ? null : editDossiers.choix }),
      })
      const d = await res.json().catch(() => ({}))
      if (!res.ok) { setDossiersErreur(d.detail ?? "Les dossiers n'ont pas pu être enregistrés."); return }
      setUsers((p) => p.map((u) => u.id === editDossiers.id ? { ...u, dossiers_mail: d.dossiers_mail } : u))
      setEditDossiers(null)
    } catch { setDossiersErreur("Le serveur n'a pas répondu. Réessayez.") } finally { setDossiersEnCours(false) }
  }
  const [adding, setAdding] = useState(false)
  const [formError, setFormError] = useState("")
  const [showForm, setShowForm] = useState(false)
  const [permLoading, setPermLoading] = useState<string | null>(null)
  // LE LIEN D'ACCÈS DÉLIVRÉ À LA MAIN (03/09) : quand le mail de connexion
  // n'arrive pas (boîte en panne, indésirables, salarié sans messagerie), ou
  // quand on installe le poste de quelqu'un à côté de lui.
  const [lienAcces, setLienAcces] = useState<
    { url: string; email: string; nom: string | null; valable_heures: number
      utilisations?: number; migration_absente?: string | null } | null>(null)
  const [lienEnCours, setLienEnCours] = useState<string | null>(null)
  const [lienErreur, setLienErreur] = useState("")
  const [copie, setCopie] = useState(false)
  // LE NOMBRE D'UTILISATIONS SE CHOISIT AVANT DE CRÉER (03/09, Noa : « PC +
  // téléphone »). Le clic sur « Lien d'accès » ouvre d'abord ce choix ; le
  // lien n'est fabriqué qu'au second clic, avec le nombre voulu.
  const [lienPour, setLienPour] = useState<{ id: string; nom: string | null; email: string } | null>(null)
  const [utilisations, setUtilisations] = useState(1)

  async function creerLienAcces(userId: string, combien: number) {
    setLienEnCours(userId); setLienErreur(""); setCopie(false)
    try {
      const res = await fetch(`${apiUrl}/api/users/${userId}/lien-connexion`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${backendToken}` },
        body: JSON.stringify({ utilisations: combien }),
      })
      const d = await res.json().catch(() => ({}))
      if (!res.ok) { setLienErreur(d.detail ?? "Le lien n'a pas pu être créé."); setLienAcces(null); return }
      setLienAcces(d); setLienPour(null)
    } catch {
      setLienErreur("Le serveur n'a pas répondu. Réessayez.")
    } finally { setLienEnCours(null) }
  }

  async function copierLien() {
    if (!lienAcces) return
    try {
      await navigator.clipboard.writeText(lienAcces.url)
      setCopie(true)
    } catch {
      // Presse-papiers refusé (contexte non sécurisé, permission) : le champ
      // reste sélectionnable, on le dit plutôt que de faire semblant.
      setLienErreur("Copie impossible ici : sélectionnez le lien et copiez-le à la main.")
    }
  }

  // « SE CONNECTER EN TANT QUE » (23/09) : super_admin seul, session courte (2 h),
  // bandeau visible tant qu'elle dure ; le serveur trace chaque ouverture.
  const [incarnation, setIncarnation] = useState<{ id: string; erreur: string } | null>(null)
  const seConnecterEnTantQue = async (u: User) => {
    setIncarnation({ id: u.id, erreur: "" })
    const r = await signIn("credentials", { incarner: backendToken, user_id: u.id, redirect: false })
    if (r?.error) { setIncarnation({ id: u.id, erreur: "Connexion refusée par le serveur." }); return }
    window.location.href = "/accueil"
  }

  const creatableRoles = CREATABLE[currentRole] ?? []

  // LE RÔLE SE CHANGE (13/09) : c'est lui qui ouvre les fonctions (matrice
  // des permissions), les documents, les connaissances et les dossiers du NAS
  // visibles — même pour deux profils qui partagent la boîte de l'entreprise.
  const [roleErreur, setRoleErreur] = useState("")
  const [roleEnCours, setRoleEnCours] = useState<string | null>(null)
  const peutChangerRole = (cible: Role) =>
    currentRole === "super_admin" ? cible !== "super_admin" : currentRole === "direction" && METIER_ROLES.includes(cible)

  async function changerRole(userId: string, role: Role) {
    setRoleEnCours(userId); setRoleErreur("")
    try {
      const res = await fetch(`${apiUrl}/api/users/${userId}/role`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${backendToken}` },
        body: JSON.stringify({ role }),
      })
      const d = await res.json().catch(() => ({}))
      if (!res.ok) { setRoleErreur(d.detail ?? "Le rôle n'a pas pu être changé."); return }
      setUsers((p) => p.map((u) => u.id === userId
        ? { ...u, role, agent_permissions: d.agent_permissions ?? u.agent_permissions } : u))
    } catch { setRoleErreur("Erreur réseau") } finally { setRoleEnCours(null) }
  }

  // LE CODE D'UNE CARTE (13/09) : obligatoire pour la direction sur la boîte
  // de l'entreprise, facultatif pour les autres. Jamais relu : on le remplace.
  const [editCode, setEditCode] = useState<{ id: string; nom: string; a_code: boolean; code: string } | null>(null)
  const [codeErreur, setCodeErreur] = useState("")
  const [codeEnCours, setCodeEnCours] = useState(false)
  // LES CODES SE VOIENT (14/09, Noa : « on doit pouvoir les voir et les
  // modifier après »). Masqués par défaut dans la liste, révélés ligne par ligne.
  const [codesVisibles, setCodesVisibles] = useState<Record<string, boolean>>({})

  // MODIFIER UN PROFIL (14/09) : son nom et son adresse.
  const [editProfil, setEditProfil] = useState<{ id: string; name: string; email: string } | null>(null)
  const [profilErreur, setProfilErreur] = useState("")
  const [profilEnCours, setProfilEnCours] = useState(false)
  async function enregistrerProfil() {
    if (!editProfil) return
    setProfilEnCours(true); setProfilErreur("")
    try {
      const res = await fetch(`${apiUrl}/api/users/${editProfil.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${backendToken}` },
        body: JSON.stringify({ name: editProfil.name, email: editProfil.email }),
      })
      const d = await res.json().catch(() => ({}))
      if (!res.ok) { setProfilErreur(d.detail ?? "Le profil n'a pas pu être modifié."); return }
      setUsers((p) => p.map((u) => u.id === editProfil.id ? { ...u, name: d.name, email: d.email } : u))
      setEditProfil(null)
    } catch { setProfilErreur("Le serveur n'a pas répondu. Réessayez.") } finally { setProfilEnCours(false) }
  }

  // SUPPRIMER COMPLÈTEMENT UN PROFIL (14/09). Désactiver le garde en base ;
  // ceci efface ses conversations, tâches, consignes… — d'où la confirmation
  // qui fait RETAPER le nom : on ne confirme bien que ce qu'on a lu.
  const [aSupprimer, setASupprimer] = useState<{ id: string; nom: string; saisie: string } | null>(null)
  const [suppressionErreur, setSuppressionErreur] = useState("")
  const [suppressionEnCours, setSuppressionEnCours] = useState(false)
  async function supprimerProfil() {
    if (!aSupprimer) return
    setSuppressionEnCours(true); setSuppressionErreur("")
    try {
      const res = await fetch(`${apiUrl}/api/users/${aSupprimer.id}`, {
        method: "DELETE", headers: { Authorization: `Bearer ${backendToken}` },
      })
      const d = await res.json().catch(() => ({}))
      if (!res.ok) { setSuppressionErreur(d.detail ?? "Le profil n'a pas pu être supprimé."); return }
      setUsers((p) => p.filter((u) => u.id !== aSupprimer.id))
      setASupprimer(null)
    } catch { setSuppressionErreur("Le serveur n'a pas répondu. Réessayez.") } finally { setSuppressionEnCours(false) }
  }
  const peutGerer = (cible: Role) => currentRole === "super_admin" || (currentRole === "direction" && METIER_ROLES.includes(cible))
  async function enregistrerCode(retirer: boolean) {
    if (!editCode) return
    setCodeEnCours(true); setCodeErreur("")
    try {
      const res = await fetch(`${apiUrl}/api/users/${editCode.id}/code`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${backendToken}` },
        body: JSON.stringify({ code: retirer ? null : editCode.code.trim() }),
      })
      const d = await res.json().catch(() => ({}))
      if (!res.ok) { setCodeErreur(d.detail ?? "Le code n'a pas pu être enregistré."); return }
      setUsers((p) => p.map((u) => u.id === editCode.id ? { ...u, a_code: !!d.a_code, code: d.code ?? null } : u))
      setEditCode(null)
    } catch { setCodeErreur("Erreur réseau") } finally { setCodeEnCours(false) }
  }
  const visibleAgents: Agent[] = ["agent1", "agent2", "agent3"].filter(
    (a) => a !== "agent3" || currentRole === "super_admin" || currentRole === "direction"
  ) as Agent[]

  async function addUser(e: React.FormEvent) {
    e.preventDefault(); setAdding(true); setFormError("")
    try {
      const { dossiers, code, ...champs } = form
      const res = await fetch(`${apiUrl}/api/users/`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${backendToken}` },
        // Avec une boîte d'entreprise reliée, un compte métier commence par la
        // réception + les dossiers cochés ; sans elle, rien n'est restreint.
        body: JSON.stringify({ ...champs, code_pin: code.trim() || null,
          dossiers_mail: boiteReliee && !ROLES_ADMIN.includes(form.role) ? dossiers : null }),
      })
      if (!res.ok) {
        const err = await res.json()
        setFormError(err.detail ?? "Erreur")
        return
      }
      const newUser = await res.json()
      setUsers((p) => [newUser, ...p])
      setForm({ email: "", name: "", role: "terrain", dossiers: [], code: "" }); setShowForm(false)
    } catch { setFormError("Erreur réseau") } finally { setAdding(false) }
  }

  async function togglePerm(userId: string, agent: Agent, cur: boolean, targetRole: Role) {
    if (!canTogglePerm(currentRole, agent, targetRole)) return
    const key = `${userId}:${agent}`; setPermLoading(key)
    try {
      const res = await fetch(`${apiUrl}/api/users/${userId}/permissions/${agent}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${backendToken}` },
        body: JSON.stringify({ has_access: !cur }),
      })
      if (res.ok) setUsers((p) => p.map((u) => u.id === userId
        ? { ...u, agent_permissions: { ...u.agent_permissions, [agent]: !cur } } : u))
    } finally { setPermLoading(null) }
  }

  async function toggleActive(userId: string, actif: boolean, targetRole: Role) {
    if (currentRole !== "super_admin" && currentRole !== "direction" && !METIER_ROLES.includes(targetRole)) return
    const ep = actif ? "deactivate" : "reactivate"
    const res = await fetch(`${apiUrl}/api/users/${userId}/${ep}`, {
      method: "PUT", headers: { Authorization: `Bearer ${backendToken}` },
    })
    if (res.ok) setUsers((p) => p.map((u) => u.id === userId ? { ...u, actif: !actif } : u))
  }

  const inp: React.CSSProperties = {
    padding: "10px 14px", border: "1.5px solid var(--marque-border)",
    borderRadius: 10, fontSize: 14, outline: "none", width: "100%",
    color: "var(--marque-text-primary)", background: "var(--marque-surface)",
  }

  return (
    <div>
      <div className="sym-in" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
        <div>
          <div style={{ fontSize: 11, fontWeight: 600, color: "var(--marque-text-muted)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
            Total
          </div>
          <div style={{ fontSize: 28, fontWeight: 800, color: "var(--marque-text-primary)" }}>
            {users.length} <span style={{ fontSize: 14, fontWeight: 500, color: "var(--marque-text-muted)" }}>utilisateurs</span>
          </div>
        </div>
        <button onClick={() => {
          // Un nouveau profil part sur la boîte de l'entreprise : c'est le cas
          // de tout le monde sauf des administrateurs (13/09).
          if (!showForm && adresseBoite && !form.email) setForm((f) => ({ ...f, email: adresseBoite }))
          setShowForm(!showForm)
        }} className="sym-tap" style={{
          background: "var(--marque-primary)", color: "var(--marque-text-on-dark)", border: "none",
          borderRadius: "var(--marque-radius-pill)", padding: "10px 22px", fontSize: 14, fontWeight: 600, cursor: "pointer",
          boxShadow: "var(--marque-shadow-card)",
        }}>
          + Ajouter un utilisateur
        </button>
      </div>

      {lienErreur && !lienAcces && (
        <p role="status" className="sym-pop" style={{ color: "var(--marque-error-text)", fontSize: 13, margin: "0 0 16px" }}>
          {lienErreur}
        </p>
      )}

      {lienPour && !lienAcces && (
        <div className="sym-fade" style={{
          background: "var(--marque-primary-subtle)", borderRadius: "var(--marque-radius-card)",
          padding: 18, marginBottom: 20, border: "1px solid var(--marque-primary-light)",
        }}>
          <div style={{ fontWeight: 700, fontSize: 14, color: "var(--marque-text-primary)", marginBottom: 4 }}>
            Lien d'accès pour {lienPour.nom || lienPour.email}
          </div>
          <p style={{ fontSize: 13, color: "var(--marque-text-body)", margin: "0 0 12px", maxWidth: 620 }}>
            Sur combien d'appareils cette personne doit-elle pouvoir l'ouvrir ? Chaque appareil
            consomme une utilisation, puis reste connecté de lui-même.
          </p>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            {[1, 2, 3, 5].map((n) => (
              <button key={n} type="button" onClick={() => setUtilisations(n)} className="sym-tap"
                aria-pressed={utilisations === n}
                style={{
                  border: utilisations === n ? "1px solid var(--marque-primary)" : "1px solid var(--marque-border)",
                  background: utilisations === n ? "var(--marque-primary)" : "var(--marque-surface)",
                  color: utilisations === n ? "var(--marque-text-on-dark)" : "var(--marque-text-body)",
                  borderRadius: "var(--marque-radius-pill)", padding: "7px 14px", fontSize: 13, cursor: "pointer",
                  fontWeight: 600,
                }}>
                {n === 1 ? "1 appareil" : `${n} appareils`}
              </button>
            ))}
            <button type="button" onClick={() => creerLienAcces(lienPour.id, utilisations)}
              disabled={lienEnCours === lienPour.id} className="sym-tap" style={{
                background: "var(--marque-primary)", color: "var(--marque-text-on-dark)", border: "none",
                borderRadius: "var(--marque-radius-pill)", padding: "9px 20px", fontSize: 13, fontWeight: 600,
                cursor: lienEnCours ? "wait" : "pointer", marginLeft: 6,
              }}>
              {lienEnCours ? "…" : "Créer le lien"}
            </button>
            <button type="button" onClick={() => { setLienPour(null); setLienErreur("") }} className="sym-tap" style={{
              background: "none", border: "1px solid var(--marque-border)", color: "var(--marque-text-body)",
              borderRadius: "var(--marque-radius-pill)", padding: "9px 18px", fontSize: 13, cursor: "pointer",
            }}>
              Annuler
            </button>
          </div>
          {lienErreur && (
            <p role="status" style={{ color: "var(--marque-error-text)", fontSize: 12, margin: "10px 0 0" }}>{lienErreur}</p>
          )}
        </div>
      )}

      {lienAcces && (
        <div className="sym-fade" style={{
          background: "var(--marque-primary-subtle)", borderRadius: "var(--marque-radius-card)",
          padding: 18, marginBottom: 20, border: "1px solid var(--marque-primary-light)",
        }}>
          <div style={{ fontWeight: 700, fontSize: 14, color: "var(--marque-text-primary)", marginBottom: 4 }}>
            Lien d'accès pour {lienAcces.nom || lienAcces.email}
          </div>
          <p style={{ fontSize: 13, color: "var(--marque-text-body)", margin: "0 0 12px", maxWidth: 620 }}>
            Remettez-le <b>à cette personne uniquement</b> : il ouvre la session à sa place.
            {(lienAcces.utilisations ?? 1) > 1
              ? <> Il fonctionne <b>{lienAcces.utilisations} fois</b> — un appareil par utilisation —</>
              : <> Il ne fonctionne <b>qu'une fois</b></>}
            {" "}et expire dans {lienAcces.valable_heures} h.
            Une fois utilisé, chaque appareil restera connecté — elle n'aura plus rien à faire.
          </p>
          {lienAcces.migration_absente && (
            <p role="status" style={{ color: "var(--marque-error-text)", fontSize: 12, margin: "0 0 10px" }}>
              Ce serveur ne sait pas encore compter les utilisations (migration 035 à appliquer) :
              ce lien ne vaudra qu'une fois.
            </p>
          )}
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <input
              readOnly
              value={lienAcces.url}
              onFocus={(e) => e.currentTarget.select()}
              style={{
                flex: "1 1 320px", padding: "9px 12px", border: "1.5px solid var(--marque-border)",
                borderRadius: 10, fontSize: 12, fontFamily: "ui-monospace, monospace",
                color: "var(--marque-text-primary)", background: "var(--marque-surface)",
              }}
            />
            <button type="button" onClick={copierLien} className="sym-tap" style={{
              background: "var(--marque-primary)", color: "var(--marque-text-on-dark)", border: "none",
              borderRadius: "var(--marque-radius-pill)", padding: "9px 20px", fontSize: 13, fontWeight: 600, cursor: "pointer",
            }}>
              {copie ? "Copié" : "Copier"}
            </button>
            <button type="button" onClick={() => { setLienAcces(null); setLienErreur(""); setCopie(false) }}
              className="sym-tap" style={{
                background: "none", border: "1px solid var(--marque-border)", color: "var(--marque-text-body)",
                borderRadius: "var(--marque-radius-pill)", padding: "9px 18px", fontSize: 13, cursor: "pointer",
              }}>
              Fermer
            </button>
          </div>
          {lienErreur && (
            <p role="status" style={{ color: "var(--marque-error-text)", fontSize: 12, margin: "10px 0 0" }}>{lienErreur}</p>
          )}
        </div>
      )}

      {editDossiers && (
        <div className="sym-fade" style={{
          background: "var(--marque-primary-subtle)", borderRadius: "var(--marque-radius-card)",
          padding: 18, marginBottom: 20, border: "1px solid var(--marque-primary-light)",
        }}>
          <div style={{ fontWeight: 700, fontSize: 14, color: "var(--marque-text-primary)", marginBottom: 4 }}>
            Dossiers du mail pour {editDossiers.nom}
          </div>
          <p style={{ fontSize: 13, color: "var(--marque-text-body)", margin: "0 0 12px", maxWidth: 640 }}>
            La boîte de réception est toujours visible. Cochez les autres dossiers de la boîte que
            ce profil peut lire ; le reste lui est fermé, dans le chat comme dans la mémoire.
          </p>
          <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13, marginBottom: 10, cursor: "pointer" }}>
            <input type="checkbox" checked={editDossiers.libres}
                   onChange={(e) => setEditDossiers((d) => d && { ...d, libres: e.target.checked })} />
            Aucune restriction (tous les dossiers)
          </label>
          {!editDossiers.libres && (boiteReliee ? (
            <CasesDossiers dossiers={dossiersBoite} choix={editDossiers.choix}
                           onChange={(choix) => setEditDossiers((d) => d && { ...d, choix })} />
          ) : (
            <p style={{ fontSize: 12, color: "var(--marque-text-muted)", margin: 0 }}>
              {dossiersErreur || "La boîte n'est pas encore reliée."} Tant qu'elle ne l'est pas, ce profil
              garde {editDossiers.choix.length ? `ses ${editDossiers.choix.length} dossier(s) déjà choisi(s)` : "la boîte de réception seule"} ;
              les autres dossiers se cocheront ici une fois la boîte reliée.
            </p>
          ))}
          <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
            <button type="button" onClick={enregistrerDossiers} disabled={dossiersEnCours} className="sym-tap" style={{
              background: "var(--marque-primary)", color: "var(--marque-text-on-dark)", border: "none",
              borderRadius: "var(--marque-radius-pill)", padding: "9px 20px", fontSize: 13, fontWeight: 600,
              cursor: dossiersEnCours ? "wait" : "pointer",
            }}>{dossiersEnCours ? "…" : "Enregistrer"}</button>
            <button type="button" onClick={() => setEditDossiers(null)} className="sym-tap" style={{
              background: "none", border: "1px solid var(--marque-border)", color: "var(--marque-text-body)",
              borderRadius: "var(--marque-radius-pill)", padding: "9px 18px", fontSize: 13, cursor: "pointer",
            }}>Annuler</button>
          </div>
        </div>
      )}

      {editCode && (
        <div className="sym-fade" style={{
          background: "var(--marque-primary-subtle)", borderRadius: "var(--marque-radius-card)",
          padding: 18, marginBottom: 20, border: "1px solid var(--marque-primary-light)",
        }}>
          <div style={{ fontWeight: 700, fontSize: 14, color: "var(--marque-text-primary)", marginBottom: 4 }}>
            Code de la carte de {editCode.nom}
          </div>
          <p style={{ fontSize: 13, color: "var(--marque-text-body)", margin: "0 0 12px", maxWidth: 640 }}>
            4 à 6 chiffres, demandés quand on clique sur cette carte à la connexion. Cinq essais
            faux bloquent la carte un quart d'heure. {editCode.a_code && !editCode.code ? "Un code est posé mais ne se relit pas (posé avant le 14/09) : le nouveau le remplace." : ""}
          </p>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <input type="text" inputMode="numeric" autoComplete="off" maxLength={6}
                   placeholder="Code" value={editCode.code}
                   onChange={(e) => setEditCode((c) => c && { ...c, code: e.target.value.replace(/\D/g, "") })}
                   style={{ ...inp, width: 160, letterSpacing: "0.3em" }} />
            <button type="button" onClick={() => enregistrerCode(false)} disabled={codeEnCours || editCode.code.length < 4}
              className="sym-tap" style={{
                background: "var(--marque-primary)", color: "var(--marque-text-on-dark)", border: "none",
                borderRadius: "var(--marque-radius-pill)", padding: "9px 20px", fontSize: 13, fontWeight: 600,
                cursor: codeEnCours ? "wait" : "pointer", opacity: editCode.code.length < 4 ? 0.6 : 1,
              }}>{codeEnCours ? "…" : "Enregistrer"}</button>
            {editCode.a_code && (
              <button type="button" onClick={() => enregistrerCode(true)} disabled={codeEnCours} className="sym-tap" style={{
                background: "none", border: "1px solid var(--marque-border)", color: "var(--marque-text-body)",
                borderRadius: "var(--marque-radius-pill)", padding: "9px 18px", fontSize: 13, cursor: "pointer",
              }}>Retirer le code</button>
            )}
            <button type="button" onClick={() => { setEditCode(null); setCodeErreur("") }} className="sym-tap" style={{
              background: "none", border: "1px solid var(--marque-border)", color: "var(--marque-text-body)",
              borderRadius: "var(--marque-radius-pill)", padding: "9px 18px", fontSize: 13, cursor: "pointer",
            }}>Annuler</button>
          </div>
          {codeErreur && <p role="status" style={{ color: "var(--marque-error-text)", fontSize: 12, margin: "10px 0 0" }}>{codeErreur}</p>}
        </div>
      )}

      {editProfil && (
        <div className="sym-fade" data-testid="modifier-profil" style={{
          background: "var(--marque-primary-subtle)", borderRadius: "var(--marque-radius-card)",
          padding: 18, marginBottom: 20, border: "1px solid var(--marque-primary-light)",
        }}>
          <div style={{ fontWeight: 700, fontSize: 14, color: "var(--marque-text-primary)", marginBottom: 10 }}>
            Modifier le profil
          </div>
          <div className="sym-grid-1" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 12 }}>
            <input type="text" placeholder="Nom (affiché sur la carte)" value={editProfil.name}
                   onChange={(e) => setEditProfil((x) => x && { ...x, name: e.target.value })} style={inp} />
            <input type="email" placeholder="Adresse" value={editProfil.email}
                   onChange={(e) => setEditProfil((x) => x && { ...x, email: e.target.value })} style={inp} />
          </div>
          <p style={{ fontSize: 12, color: "var(--marque-text-muted)", margin: "0 0 12px" }}>
            Le rôle se change dans la liste ; le code et les dossiers du mail ont leur bouton sur la ligne.
          </p>
          <div style={{ display: "flex", gap: 8 }}>
            <button type="button" onClick={enregistrerProfil} disabled={profilEnCours} className="sym-tap" style={{
              background: "var(--marque-primary)", color: "var(--marque-text-on-dark)", border: "none",
              borderRadius: "var(--marque-radius-pill)", padding: "9px 20px", fontSize: 13, fontWeight: 600,
              cursor: profilEnCours ? "wait" : "pointer",
            }}>{profilEnCours ? "…" : "Enregistrer"}</button>
            <button type="button" onClick={() => { setEditProfil(null); setProfilErreur("") }} className="sym-tap" style={{
              background: "none", border: "1px solid var(--marque-border)", color: "var(--marque-text-body)",
              borderRadius: "var(--marque-radius-pill)", padding: "9px 18px", fontSize: 13, cursor: "pointer",
            }}>Annuler</button>
          </div>
          {profilErreur && <p role="status" style={{ color: "var(--marque-error-text)", fontSize: 12, margin: "10px 0 0" }}>{profilErreur}</p>}
        </div>
      )}

      {aSupprimer && (
        <div className="sym-fade" data-testid="supprimer-profil" style={{
          background: "var(--marque-surface)", borderRadius: "var(--marque-radius-card)",
          padding: 18, marginBottom: 20, border: "1px solid var(--marque-error-text)",
        }}>
          <div style={{ fontWeight: 700, fontSize: 14, color: "var(--marque-error-text)", marginBottom: 4 }}>
            Supprimer définitivement {aSupprimer.nom}
          </div>
          <p style={{ fontSize: 13, color: "var(--marque-text-body)", margin: "0 0 12px", maxWidth: 640 }}>
            Le profil disparaît avec <b>tout ce qui n'appartient qu'à lui</b> : ses conversations, ses tâches,
            ses consignes, ses validations et ses appareils connectés. Le journal garde la trace de ses actions,
            sans son nom. <b>Rien ne pourra être récupéré.</b> Pour seulement lui couper l'accès, utilisez « Désactiver ».
          </p>
          <div style={{ fontSize: 12, color: "var(--marque-text-muted)", marginBottom: 6 }}>
            Pour confirmer, retapez le nom : <b>{aSupprimer.nom}</b>
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <input type="text" value={aSupprimer.saisie} aria-label="Nom du profil à supprimer"
                   onChange={(e) => setASupprimer((x) => x && { ...x, saisie: e.target.value })}
                   style={{ ...inp, maxWidth: 260 }} />
            <button type="button" onClick={supprimerProfil}
                    disabled={suppressionEnCours || aSupprimer.saisie.trim() !== aSupprimer.nom.trim()}
                    className="sym-tap" style={{
                      background: "var(--marque-error-text)", color: "var(--marque-text-on-dark)", border: "none",
                      borderRadius: "var(--marque-radius-pill)", padding: "9px 20px", fontSize: 13, fontWeight: 600,
                      cursor: suppressionEnCours ? "wait" : "pointer",
                      opacity: aSupprimer.saisie.trim() === aSupprimer.nom.trim() ? 1 : 0.5,
                    }}>{suppressionEnCours ? "…" : "Supprimer définitivement"}</button>
            <button type="button" onClick={() => { setASupprimer(null); setSuppressionErreur("") }} className="sym-tap" style={{
              background: "none", border: "1px solid var(--marque-border)", color: "var(--marque-text-body)",
              borderRadius: "var(--marque-radius-pill)", padding: "9px 18px", fontSize: 13, cursor: "pointer",
            }}>Annuler</button>
          </div>
          {suppressionErreur && <p role="status" style={{ color: "var(--marque-error-text)", fontSize: 12, margin: "10px 0 0" }}>{suppressionErreur}</p>}
        </div>
      )}

      {roleErreur && (
        <p role="status" className="sym-pop" style={{ color: "var(--marque-error-text)", fontSize: 13, margin: "0 0 16px" }}>
          {roleErreur}
        </p>
      )}

      {showForm && (
        <form onSubmit={addUser} className="sym-fade" style={{
          background: "var(--marque-primary-subtle)", borderRadius: "var(--marque-radius-card)", padding: 20,
          marginBottom: 20, border: "1px solid var(--marque-primary-light)",
        }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: "var(--marque-primary)", marginBottom: 14 }}>
            Nouvel utilisateur
          </div>
          <div className="sym-grid-1" style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12, marginBottom: 12 }}>
            <input type="email" placeholder="Email *" required value={form.email}
              onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))} style={inp} />
            <input type="text" placeholder={prenomRequis ? "Nom (affiché sur la carte) *" : "Nom complet"}
              required={prenomRequis} value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} style={inp} />
            <select value={form.role} onChange={(e) => setForm((f) => ({ ...f, role: e.target.value as Role }))} style={inp}>
              {creatableRoles.map((r) => <option key={r} value={r}>{ROLE_LABELS[r]}</option>)}
            </select>
          </div>
          {surLaBoite ? (
            <p style={{ fontSize: 12.5, color: "var(--marque-text-body)", margin: "0 0 12px" }}>
              C'est l'adresse de la <b>boîte de l'entreprise</b> : ce profil lira le mail avec les dossiers
              cochés ci-dessous. Son <b>rôle</b> décide de ce qu'il voit.
            </p>
          ) : adresseDejaPortee ? (
            <p style={{ fontSize: 12.5, color: "var(--marque-text-body)", margin: "0 0 12px" }}>
              Cette adresse est déjà utilisée : ce sera un <b>profil de plus</b> sur la même adresse,
              avec son propre chat et ses propres documents.
            </p>
          ) : null}
          {/* LA CARTE ET SON CODE, BOÎTE RELIÉE OU NON (14/09, Noa : « chacun peut se
              connecter avec son prénom même si l'adresse mail n'est pas configurée »). */}
          {form.role !== "super_admin" && (
            <div style={{ display: "flex", gap: 10, alignItems: "center", margin: "0 0 12px", flexWrap: "wrap" }}>
              <input type="text" inputMode="numeric" autoComplete="off" maxLength={6}
                     placeholder={form.role === "direction" ? "Code de la carte (4 à 6 chiffres)" : "Code de la carte (facultatif)"}
                     pattern="\d{4,6}" value={form.code}
                     onChange={(e) => setForm((f) => ({ ...f, code: e.target.value.replace(/\D/g, "") }))}
                     style={{ ...inp, maxWidth: 280, letterSpacing: form.code ? "0.3em" : undefined }} />
              <span style={{ fontSize: 12, color: "var(--marque-text-muted)" }}>
                demandé au clic sur sa carte de connexion
                {form.role === "direction" && " — sans code, la direction n'a pas de carte et entre par le lien magique"}
              </span>
            </div>
          )}
          {!ROLES_ADMIN.includes(form.role) && (boiteReliee ? (
            <div style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 12.5, fontWeight: 600, color: "var(--marque-text-primary)", marginBottom: 6 }}>
                Dossiers du mail visibles <span style={{ fontWeight: 400, color: "var(--marque-text-muted)" }}>— la boîte de réception l'est toujours</span>
              </div>
              <CasesDossiers dossiers={dossiersBoite} choix={form.dossiers}
                             onChange={(choix) => setForm((f) => ({ ...f, dossiers: choix }))} />
            </div>
          ) : (
            <p style={{ fontSize: 12, color: "var(--marque-text-muted)", margin: "0 0 12px" }}>
              Dossiers du mail : {dossiersErreur || "la boîte n'est pas encore reliée."} Le profil peut être
              créé maintenant ; ses dossiers se choisiront plus tard, avec le bouton « Dossiers mail » de sa ligne.
            </p>
          ))}
          {formError && <p style={{ color: "var(--marque-error-text)", fontSize: 13, margin: "0 0 10px" }}>{formError}</p>}
          <div style={{ display: "flex", gap: 8 }}>
            <button type="submit" disabled={adding} className="sym-tap" style={{
              background: "var(--marque-primary)", color: "var(--marque-text-on-dark)", border: "none",
              borderRadius: "var(--marque-radius-pill)", padding: "9px 20px", fontSize: 13, fontWeight: 600,
              cursor: adding ? "not-allowed" : "pointer", opacity: adding ? 0.7 : 1,
            }}>
              {adding ? "Ajout..." : "Ajouter"}
            </button>
            <button type="button" onClick={() => setShowForm(false)} className="sym-tap" style={{
              background: "var(--marque-surface)", color: "var(--marque-text-body)", border: "1px solid var(--marque-border)",
              borderRadius: "var(--marque-radius-pill)", padding: "9px 20px", fontSize: 13, cursor: "pointer",
            }}>
              Annuler
            </button>
          </div>
        </form>
      )}

      <div className="sym-card sym-in sym-in-1" style={{ background: "var(--marque-surface)", borderRadius: "var(--marque-radius-card)", boxShadow: "var(--marque-shadow-card)", overflow: "hidden" }}>
        {/* Sept colonnes sur un téléphone : sans ce conteneur, les dernières
            sont coupées par l'`overflow: hidden` de la carte et rien ne permet
            d'y accéder. Les deux autres tables de cet écran l'avaient déjà. */}
        <div className="sym-table-large" style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 640 }}>
          <thead>
            <tr style={{ borderBottom: "1px solid var(--marque-border)", background: "var(--marque-canvas)" }}>
              {["Utilisateur", "Rôle", ...visibleAgents.map((a) => nomExpert(a, true)), "Dossiers mail", "Code", "Statut", ""].map((h, i) => (
                <th key={i} style={{ padding: "11px 16px", textAlign: "left", fontSize: 11, fontWeight: 700, color: "var(--marque-text-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {users.map((user) => {
              const color = ROLE_COLORS[user.role] || "#666"
              return (
                <tr key={user.id} style={{ borderBottom: "1px solid var(--marque-border)", opacity: user.actif ? 1 : 0.45 }}>
                  <td style={{ padding: "14px 16px" }}>
                    <div style={{ fontWeight: 600, fontSize: 14, color: "var(--marque-text-primary)" }}>{user.name || "Sans nom"}</div>
                    <div style={{ fontSize: 12, color: "var(--marque-text-muted)", marginTop: 1 }}>
                      {user.email}
                      {users.filter((u) => u.email.toLowerCase() === user.email.toLowerCase()).length > 1 && (
                        <span title={adresseBoite && user.email.toLowerCase() === adresseBoite.toLowerCase()
                                ? "Profil de la boîte de l'entreprise : sa carte est sur la page de connexion"
                                : "Plusieurs profils sur cette adresse : chacun choisit son prénom après le lien magique"}
                              style={{ marginLeft: 6, fontSize: 11, fontWeight: 600, color: "var(--marque-primary)" }}>· boîte partagée</span>
                      )}
                    </div>
                  </td>
                  <td style={{ padding: "14px 16px" }}>
                    {peutChangerRole(user.role) ? (
                      <select value={user.role} disabled={roleEnCours === user.id} aria-label={`Rôle de ${user.name || user.email}`}
                              onChange={(e) => changerRole(user.id, e.target.value as Role)}
                              style={{ background: color + "18", color, border: "none", padding: "4px 8px",
                                       borderRadius: "var(--marque-radius-pill)", fontSize: 12, fontWeight: 600,
                                       cursor: roleEnCours === user.id ? "wait" : "pointer" }}>
                        {Array.from(new Set([user.role, ...creatableRoles])).map((r) => (
                          <option key={r} value={r}>{ROLE_LABELS[r]}</option>
                        ))}
                      </select>
                    ) : (
                      <span style={{ background: color + "18", color, padding: "3px 10px", borderRadius: "var(--marque-radius-pill)", fontSize: 12, fontWeight: 600 }}>
                        {ROLE_LABELS[user.role]}
                      </span>
                    )}
                  </td>
                  {visibleAgents.map((agent) => {
                    const has = user.agent_permissions[agent]
                    const canToggle = canTogglePerm(currentRole, agent, user.role)
                    const loading = permLoading === `${user.id}:${agent}`
                    return (
                      <td key={agent} style={{ padding: "14px 16px", textAlign: "center" }}>
                        <button
                          onClick={() => canToggle && togglePerm(user.id, agent, has, user.role)}
                          disabled={!canToggle || loading}
                          title={!canToggle ? "Permission insuffisante" : has ? "Révoquer" : "Accorder"}
                          className="sym-tap"
                          style={{
                            width: 40, height: 22, borderRadius: 11, border: "none",
                            background: has ? "var(--marque-primary-mid)" : "var(--marque-border)",
                            cursor: canToggle ? "pointer" : "default",
                            position: "relative", transition: "background 0.25s ease",
                            opacity: loading ? 0.5 : 1,
                          }}
                        >
                          <span style={{
                            position: "absolute", top: 3,
                            left: has ? 21 : 3, width: 16, height: 16,
                            borderRadius: "50%", background: "var(--marque-surface)",
                            transition: "left 0.2s", boxShadow: "0 1px 3px rgba(0,0,0,0.2)",
                          }} />
                        </button>
                      </td>
                    )
                  })}
                  {(
                    <td style={{ padding: "14px 16px", whiteSpace: "nowrap" }}>
                      {ROLES_ADMIN.includes(user.role) ? (
                        <span style={{ fontSize: 12, color: "var(--marque-text-muted)" }}>Tous les dossiers</span>
                      ) : (
                        <button type="button" className="sym-tap" title="Choisir les dossiers visibles"
                                onClick={() => setEditDossiers({ id: user.id, nom: user.name || user.email,
                                                                 libres: user.dossiers_mail == null,
                                                                 choix: user.dossiers_mail || [] })}
                                style={{ background: "none", border: "1px solid var(--marque-border)", borderRadius: "var(--marque-radius-pill)",
                                         padding: "5px 12px", fontSize: 12, cursor: "pointer", color: "var(--marque-text-body)" }}>
                          {resumeDossiers(user.dossiers_mail, user.role)}
                        </button>
                      )}
                    </td>
                  )}
                  <td style={{ padding: "14px 16px", whiteSpace: "nowrap" }} data-testid="code-profil">
                    {user.role === "super_admin" ? (
                      <span style={{ fontSize: 12, color: "var(--marque-text-muted)" }}>—</span>
                    ) : !user.a_code ? (
                      peutGerer(user.role) ? (
                        <button type="button" className="sym-tap"
                                onClick={() => { setCodeErreur(""); setEditCode({ id: user.id, nom: user.name || user.email, a_code: false, code: "" }) }}
                                style={{ background: "none", border: "1px dashed var(--marque-border)", borderRadius: "var(--marque-radius-pill)",
                                         padding: "5px 12px", fontSize: 12, cursor: "pointer", color: "var(--marque-text-muted)" }}>
                          Poser un code
                        </button>
                      ) : <span style={{ fontSize: 12, color: "var(--marque-text-muted)" }}>Aucun</span>
                    ) : (
                      <span style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
                        <span style={{ fontFamily: "ui-monospace, monospace", fontSize: 13, letterSpacing: "0.15em",
                                       color: "var(--marque-text-primary)" }}>
                          {user.code ? (codesVisibles[user.id] ? user.code : "•".repeat(user.code.length)) : "posé · illisible"}
                        </span>
                        {user.code && (
                          <button type="button" className="sym-tap" aria-label={codesVisibles[user.id] ? "Masquer le code" : "Voir le code"}
                                  onClick={() => setCodesVisibles((v) => ({ ...v, [user.id]: !v[user.id] }))}
                                  style={{ background: "none", border: "none", cursor: "pointer", fontSize: 12, color: "var(--marque-primary)", padding: 0 }}>
                            {codesVisibles[user.id] ? "masquer" : "voir"}
                          </button>
                        )}
                        {peutGerer(user.role) && (
                          <button type="button" className="sym-tap"
                                  onClick={() => { setCodeErreur(""); setEditCode({ id: user.id, nom: user.name || user.email, a_code: true, code: user.code || "" }) }}
                                  style={{ background: "none", border: "none", cursor: "pointer", fontSize: 12, color: "var(--marque-primary)", padding: 0 }}>
                            modifier
                          </button>
                        )}
                      </span>
                    )}
                  </td>
                  <td style={{ padding: "14px 16px" }}>
                    <span style={{
                      fontSize: 12, fontWeight: 600, padding: "3px 10px", borderRadius: "var(--marque-radius-pill)",
                      color: user.actif ? "var(--marque-paid-text)" : "var(--marque-text-muted)",
                      background: user.actif ? "var(--marque-paid-bg)" : "var(--marque-canvas)",
                    }}>
                      {user.actif ? "● Actif" : "○ Inactif"}
                    </span>
                  </td>
                  <td style={{ padding: "14px 16px", textAlign: "right", whiteSpace: "nowrap" }}>
                    {/* Le lien d'accès : le seul recours quand le mail de
                        connexion n'arrive pas. Même hiérarchie que la
                        désactivation — la direction n'atteint pas un
                        super_admin, et le serveur le revérifie de toute façon. */}
                    {/* « Lien d'accès » retiré (15/09) : c'est un lien magique, coupé chez
                        Duret — chaque profil entre par sa carte et son code. */}
                    {peutGerer(user.role) && (
                      <button onClick={() => { setProfilErreur(""); setEditProfil({ id: user.id, name: user.name || "", email: user.email }) }}
                        className="sym-tap" title="Modifier le nom et l'adresse"
                        style={{
                          background: "none", border: "1px solid var(--marque-border)",
                          borderRadius: "var(--marque-radius-pill)", padding: "5px 14px", fontSize: 12,
                          cursor: "pointer", color: "var(--marque-text-body)", fontWeight: 500, marginRight: 8,
                        }}>
                        Modifier
                      </button>
                    )}
                    {currentRole === "super_admin" && user.role !== "super_admin" && user.actif && (
                      <button onClick={() => seConnecterEnTantQue(user)} className="sym-tap"
                        title="Ouvrir sa session pour 2 h, sans son code — tracé dans le journal"
                        disabled={incarnation?.id === user.id && !incarnation.erreur}
                        style={{
                          background: "none", border: "1px solid var(--marque-border)",
                          borderRadius: "var(--marque-radius-pill)", padding: "5px 14px", fontSize: 12,
                          cursor: "pointer", color: "var(--marque-primary)", fontWeight: 600, marginRight: 8,
                        }}>
                        {incarnation?.id === user.id && !incarnation.erreur ? "…" : "Se connecter en tant que"}
                      </button>
                    )}
                    {incarnation?.id === user.id && incarnation.erreur && (
                      <span style={{ fontSize: 12, color: "var(--marque-error-text)", marginRight: 8 }}>{incarnation.erreur}</span>
                    )}
                    {(currentRole === "super_admin" || currentRole === "direction" || METIER_ROLES.includes(user.role)) && (
                      <button onClick={() => toggleActive(user.id, user.actif, user.role)} className="sym-tap" style={{
                        background: "none", border: "1px solid var(--marque-border)",
                        borderRadius: "var(--marque-radius-pill)", padding: "5px 14px", fontSize: 12, cursor: "pointer",
                        color: "var(--marque-text-body)", fontWeight: 500,
                      }}>
                        {user.actif ? "Désactiver" : "Réactiver"}
                      </button>
                    )}
                    {peutGerer(user.role) && (
                      <button onClick={() => { setSuppressionErreur(""); setASupprimer({ id: user.id, nom: user.name || user.email, saisie: "" }) }}
                        className="sym-tap" title="Supprimer définitivement ce profil" data-testid="bouton-supprimer"
                        style={{
                          background: "none", border: "1px solid var(--marque-border)",
                          borderRadius: "var(--marque-radius-pill)", padding: "5px 14px", fontSize: 12, cursor: "pointer",
                          color: "var(--marque-error-text)", fontWeight: 500, marginLeft: 8,
                        }}>
                        Supprimer
                      </button>
                    )}
                  </td>
                </tr>
              )
            })}
            {users.length === 0 && (
              <tr><td colSpan={8} style={{ padding: 40, textAlign: "center", color: "var(--marque-text-muted)", fontSize: 14 }}>
                Aucun utilisateur à afficher.
              </td></tr>
            )}
          </tbody>
        </table>
        </div>
      </div>
    </div>
  )
}

/* ---------- PLAGES HORAIRES TAB (éditable) ---------- */
function PlagesTab({ apiUrl, backendToken, users, currentRole }: { apiUrl: string; backendToken: string; users: any[]; currentRole: string }) {
  const HOURS = Array.from({ length: 24 }, (_, i) => i)
  const [glob, setGlob] = useState<{ start_hour: number; end_hour: number } | null>(null)
  const [savingG, setSavingG] = useState(false)
  const [msgG, setMsgG] = useState("")
  const [rows, setRows] = useState<any[]>(() => users.map((u) => ({ ...u })))
  const [savingU, setSavingU] = useState<string | null>(null)
  const [msgU, setMsgU] = useState<Record<string, string>>({})

  useEffect(() => {
    fetch(`${apiUrl}/api/settings/schedule`, { headers: { Authorization: `Bearer ${backendToken}` } })
      .then((r) => (r.ok ? r.json() : null)).then((g) => g && setGlob(g)).catch(() => {})
  }, [apiUrl, backendToken])

  async function saveGlobal() {
    if (!glob) return
    setSavingG(true); setMsgG("")
    try {
      const res = await fetch(`${apiUrl}/api/settings/schedule`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${backendToken}` },
        body: JSON.stringify(glob),
      })
      if (!res.ok) { const e = await res.json().catch(() => ({})); setMsgG(e.detail || "Erreur"); return }
      setMsgG("✓ Enregistré"); setTimeout(() => setMsgG(""), 2000)
    } catch { setMsgG("Erreur réseau") } finally { setSavingG(false) }
  }

  function canEditUser(targetRole: string) {
    if (currentRole === "super_admin") return true
    if (currentRole === "direction") return !["super_admin", "direction"].includes(targetRole)
    return false
  }
  function patch(id: string, p: any) { setRows((rs) => rs.map((r) => (r.id === id ? { ...r, ...p } : r))) }

  async function saveUser(u: any) {
    setSavingU(u.id); setMsgU((m) => ({ ...m, [u.id]: "" }))
    const num = (v: any) => (v === "" || v == null ? null : Number(v))
    try {
      const res = await fetch(`${apiUrl}/api/users/${u.id}/schedule`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${backendToken}` },
        body: JSON.stringify({ schedule_start_hour: num(u.schedule_start_hour), schedule_end_hour: num(u.schedule_end_hour), bypass_schedule: !!u.bypass_schedule }),
      })
      if (!res.ok) { const e = await res.json().catch(() => ({})); setMsgU((m) => ({ ...m, [u.id]: e.detail || "Erreur" })); return }
      setMsgU((m) => ({ ...m, [u.id]: "✓" })); setTimeout(() => setMsgU((m) => ({ ...m, [u.id]: "" })), 2000)
    } catch { setMsgU((m) => ({ ...m, [u.id]: "Erreur" })) } finally { setSavingU(null) }
  }

  const inp: React.CSSProperties = { width: 56, padding: "6px 8px", border: "1.5px solid var(--marque-border)", borderRadius: 8, fontSize: 13, outline: "none", background: "var(--marque-surface)", color: "var(--marque-text-primary)" }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      {/* Plage globale */}
      <div className="sym-card sym-in" style={{ background: "var(--marque-surface)", borderRadius: "var(--marque-radius-card)", padding: 20, boxShadow: "var(--marque-shadow-card)" }}>
        <div style={{ fontSize: 11, fontWeight: 600, color: "var(--marque-text-muted)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 4 }}>Horaires</div>
        <div style={{ fontSize: 15, fontWeight: 700, color: "var(--marque-text-primary)", marginBottom: 4 }}>Plage horaire globale</div>
        <div style={{ fontSize: 12, color: "var(--marque-text-muted)", marginBottom: 14 }}>
          Appliquée à tout utilisateur sans réglage individuel. super_admin et direction sont exemptés.
        </div>
        {glob ? (
          <div style={{ display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
            <label style={{ fontSize: 13, color: "var(--marque-text-body)", display: "flex", alignItems: "center", gap: 8 }}>
              Début <input type="number" min={0} max={23} value={glob.start_hour} onChange={(e) => setGlob({ ...glob, start_hour: parseInt(e.target.value) || 0 })} style={inp} /> h
            </label>
            <label style={{ fontSize: 13, color: "var(--marque-text-body)", display: "flex", alignItems: "center", gap: 8 }}>
              Fin <input type="number" min={1} max={24} value={glob.end_hour} onChange={(e) => setGlob({ ...glob, end_hour: parseInt(e.target.value) || 1 })} style={inp} /> h
            </label>
            <button onClick={saveGlobal} disabled={savingG} className="sym-tap" style={{ background: "var(--marque-primary)", color: "var(--marque-text-on-dark)", border: "none", borderRadius: "var(--marque-radius-pill)", padding: "8px 20px", fontSize: 13, fontWeight: 600, cursor: "pointer" }}>
              {savingG ? "..." : "Enregistrer"}
            </button>
            {msgG && <span className="sym-pop" style={{ fontSize: 13, fontWeight: 600, color: msgG.startsWith("✓") ? "var(--marque-paid-text)" : "var(--marque-error-text)" }}>{msgG}</span>}
          </div>
        ) : <div style={{ color: "var(--marque-text-muted)", fontSize: 13 }}>Chargement…</div>}

        {glob && (
          <div style={{ marginTop: 16, display: "flex", gap: 3, alignItems: "flex-end", flexWrap: "wrap" }}>
            {HOURS.map((h) => {
              const active = h >= glob.start_hour && h < glob.end_hour
              return (
                <div key={h} style={{ textAlign: "center" }}>
                  <div style={{ width: 20, height: 26, borderRadius: 4, background: active ? "var(--marque-primary-mid)" : "var(--marque-border)", opacity: active ? 0.9 : 0.4, transition: "background 0.25s ease, opacity 0.25s ease" }} />
                  <div style={{ fontSize: 9, color: "var(--marque-text-muted)", marginTop: 2 }}>{h}</div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Réglages par utilisateur */}
      <div className="sym-card sym-in sym-in-1" style={{ background: "var(--marque-surface)", borderRadius: "var(--marque-radius-card)", boxShadow: "var(--marque-shadow-card)", overflow: "hidden" }}>
        <div style={{ padding: "16px 20px", borderBottom: "1px solid var(--marque-border)", fontSize: 15, fontWeight: 700, color: "var(--marque-text-primary)" }}>
          Réglages individuels <span style={{ fontWeight: 400, fontSize: 12, color: "var(--marque-text-muted)" }}>(vide = plage globale)</span>
        </div>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ background: "var(--marque-canvas)" }}>
                {["Utilisateur", "Rôle", "Début", "Fin", "24/7", ""].map((h, i) => (
                  <th key={i} style={{ padding: "10px 16px", textAlign: "left", fontSize: 11, fontWeight: 700, color: "var(--marque-text-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((u) => {
                const editable = canEditUser(u.role)
                return (
                  <tr key={u.id} style={{ borderTop: "1px solid var(--marque-border)", opacity: editable ? 1 : 0.55 }}>
                    <td style={{ padding: "12px 16px" }}>
                      <div style={{ fontWeight: 600, fontSize: 13, color: "var(--marque-text-primary)" }}>{u.name || "Sans nom"}</div>
                      <div style={{ fontSize: 11, color: "var(--marque-text-muted)" }}>{u.email}</div>
                    </td>
                    <td style={{ padding: "12px 16px" }}>
                      <span style={{ background: (ROLE_COLORS[u.role] || "#666") + "18", color: ROLE_COLORS[u.role] || "#666", padding: "3px 10px", borderRadius: "var(--marque-radius-pill)", fontSize: 12, fontWeight: 600 }}>{ROLE_LABELS[u.role]}</span>
                    </td>
                    <td style={{ padding: "12px 16px" }}>
                      <input type="number" min={0} max={23} value={u.schedule_start_hour ?? ""} disabled={!editable || u.bypass_schedule} onChange={(e) => patch(u.id, { schedule_start_hour: e.target.value })} style={inp} />
                    </td>
                    <td style={{ padding: "12px 16px" }}>
                      <input type="number" min={1} max={24} value={u.schedule_end_hour ?? ""} disabled={!editable || u.bypass_schedule} onChange={(e) => patch(u.id, { schedule_end_hour: e.target.value })} style={inp} />
                    </td>
                    <td style={{ padding: "12px 16px" }}>
                      <button onClick={() => editable && patch(u.id, { bypass_schedule: !u.bypass_schedule })} disabled={!editable} className="sym-tap" style={{ width: 40, height: 22, borderRadius: 11, border: "none", background: u.bypass_schedule ? "var(--marque-primary-mid)" : "var(--marque-border)", cursor: editable ? "pointer" : "default", position: "relative", transition: "background 0.25s ease" }}>
                        <span style={{ position: "absolute", top: 3, left: u.bypass_schedule ? 21 : 3, width: 16, height: 16, borderRadius: "50%", background: "var(--marque-surface)", transition: "left 0.2s", boxShadow: "0 1px 3px rgba(0,0,0,0.2)" }} />
                      </button>
                    </td>
                    <td style={{ padding: "12px 16px", textAlign: "right", whiteSpace: "nowrap" }}>
                      {editable && (
                        <button onClick={() => saveUser(u)} disabled={savingU === u.id} className="sym-tap" style={{ background: "none", border: "1px solid var(--marque-border)", borderRadius: "var(--marque-radius-pill)", padding: "5px 14px", fontSize: 12, cursor: "pointer", color: "var(--marque-text-body)", fontWeight: 500 }}>
                          {savingU === u.id ? "..." : "Enregistrer"}
                        </button>
                      )}
                      {msgU[u.id] && <span className="sym-pop" style={{ marginLeft: 8, fontSize: 12, fontWeight: 600, color: msgU[u.id] === "✓" ? "var(--marque-paid-text)" : "var(--marque-error-text)" }}>{msgU[u.id]}</span>}
                    </td>
                  </tr>
                )
              })}
              {rows.length === 0 && <tr><td colSpan={6} style={{ padding: 30, textAlign: "center", color: "var(--marque-text-muted)", fontSize: 13 }}>Aucun utilisateur</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

/* ---------- RBAC TAB (matrice éditable) ---------- */
function RBACTab({ apiUrl, backendToken }: { apiUrl: string; backendToken: string }) {
  const [data, setData] = useState<any>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [err, setErr] = useState("")

  useEffect(() => {
    fetch(`${apiUrl}/api/settings/permissions`, { headers: { Authorization: `Bearer ${backendToken}` } })
      .then((r) => (r.ok ? r.json() : null)).then((d) => (d ? setData(d) : setErr("Chargement impossible"))).catch(() => setErr("Erreur de chargement"))
  }, [apiUrl, backendToken])

  async function toggle(role: string, feature: string, current: boolean) {
    if (!data?.can_edit || role === data.protected_role) return
    const key = `${role}:${feature}`; setBusy(key)
    const set = (val: boolean) => setData((d: any) => ({ ...d, matrix: { ...d.matrix, [role]: { ...d.matrix[role], [feature]: val } } }))
    set(!current)  // optimiste
    try {
      const res = await fetch(`${apiUrl}/api/settings/permissions`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${backendToken}` },
        body: JSON.stringify({ role, feature, allowed: !current }),
      })
      if (!res.ok) set(current)  // rollback
    } catch { set(current) } finally { setBusy(null) }
  }

  if (err) return <div className="sym-fade" style={{ color: "var(--marque-error-text)", fontSize: 14, padding: 20 }}>{err}</div>
  if (!data) return <div className="sym-skeleton" style={{ height: 200, borderRadius: "var(--marque-radius-card)" }} />
  const canEdit = !!data.can_edit

  // UNE LIGNE PAR PERMISSION, UNE COLONNE PAR RÔLE (14/09, Noa : « des
  // permissions concrètes et compréhensibles pour un profil terrain »). Avant :
  // dix-sept colonnes au nom technique, dont cinq ne commandaient rien. Chaque
  // ligne dit maintenant ce qu'elle ouvre, en une phrase.
  const groupes: { groupe: string; features: string[] }[] =
    data.groupes || [{ groupe: "Permissions", features: data.features }]

  return (
    <div>
      <div className="sym-card sym-in" style={{ background: "var(--marque-surface)", borderRadius: "var(--marque-radius-card)", boxShadow: "var(--marque-shadow-card)", overflow: "hidden" }}>
        <div style={{ padding: "16px 24px", borderBottom: "1px solid var(--marque-border)", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
          <div>
            <div style={{ fontSize: 15, fontWeight: 700, color: "var(--marque-text-primary)" }}>Ce que chaque rôle peut faire</div>
            <div style={{ fontSize: 12, color: "var(--marque-text-muted)", marginTop: 2, maxWidth: 620 }}>
              {canEdit ? "Cliquez sur une case pour ouvrir ou fermer une permission à tout un rôle. Le super admin a toujours tout." : "Lecture seule : seul le super admin modifie ces permissions."}
              {" "}L'accès aux experts se règle personne par personne dans l'onglet Utilisateurs.
            </div>
          </div>
          <span className="sym-pop" style={{ fontSize: 11, fontWeight: 600, padding: "4px 12px", borderRadius: "var(--marque-radius-pill)", color: canEdit ? "var(--marque-paid-text)" : "var(--marque-pending-text)", background: canEdit ? "var(--marque-paid-bg)" : "var(--marque-pending-bg)" }}>
            {canEdit ? "Modifiable" : "Lecture seule"}
          </span>
        </div>
        <div style={{ overflowX: "auto" }}>
          <table data-testid="matrice-permissions" style={{ borderCollapse: "collapse", width: "100%", minWidth: 760 }}>
            <thead>
              <tr style={{ background: "var(--marque-canvas)" }}>
                <th style={{ padding: "12px 16px", textAlign: "left", fontSize: 11, fontWeight: 700, color: "var(--marque-text-muted)", textTransform: "uppercase", position: "sticky", left: 0, background: "var(--marque-canvas)", minWidth: 260 }}>Permission</th>
                {data.roles.map((role: string) => {
                  const color = ROLE_COLORS[role] || "#666"
                  return (
                    <th key={role} style={{ padding: "10px 8px", textAlign: "center", whiteSpace: "nowrap" }}>
                      <span style={{ background: color + "18", color, padding: "3px 10px", borderRadius: "var(--marque-radius-pill)", fontSize: 11.5, fontWeight: 700 }}>{ROLE_LABELS[role] || role}</span>
                    </th>
                  )
                })}
              </tr>
            </thead>
            <tbody>
              {groupes.map((g) => (
                <Fragment key={g.groupe}>
                  <tr style={{ borderTop: "1px solid var(--marque-border)" }}>
                    <td colSpan={data.roles.length + 1} style={{ padding: "14px 16px 4px", fontSize: 11, fontWeight: 700, letterSpacing: ".08em", textTransform: "uppercase", color: "var(--marque-primary)" }}>
                      {g.groupe}
                    </td>
                  </tr>
                  {g.features.map((f: string) => (
                    <tr key={f} style={{ borderTop: "1px solid var(--marque-border)" }}>
                      <td style={{ padding: "10px 16px", position: "sticky", left: 0, background: "var(--marque-surface)", maxWidth: 320 }}>
                        <div style={{ fontSize: 13.5, fontWeight: 600, color: "var(--marque-text-primary)" }}>{data.labels[f] || f}</div>
                        {data.descriptions?.[f] && (
                          <div style={{ fontSize: 12, color: "var(--marque-text-muted)", marginTop: 2, lineHeight: 1.45 }}>{data.descriptions[f]}</div>
                        )}
                      </td>
                      {data.roles.map((role: string) => {
                        const has = !!data.matrix[role]?.[f]
                        const key = `${role}:${f}`
                        const locked = role === data.protected_role
                        const reglable = locked || !data.roles_reglables?.[f] || data.roles_reglables[f].includes(role)
                        if (!reglable) return (
                          <td key={role} style={{ padding: "8px", textAlign: "center", color: "var(--marque-text-muted)", fontSize: 12 }}
                              title="Réservé à la direction : ses écrans ne s'ouvrent pas à ce rôle">—</td>
                        )
                        const editable = canEdit && !locked
                        return (
                          <td key={role} style={{ padding: "8px", textAlign: "center" }}>
                            <button
                              onClick={() => editable && toggle(role, f, has)}
                              disabled={!editable || busy === key}
                              aria-label={`${data.labels[f] || f} — ${ROLE_LABELS[role] || role} : ${has ? "oui" : "non"}`}
                              title={locked ? "Super admin : a toujours tout" : editable ? (has ? "Fermer pour ce rôle" : "Ouvrir pour ce rôle") : "Lecture seule"}
                              className="sym-tap"
                              style={{
                                width: 28, height: 28, borderRadius: 8, border: "none", fontSize: 14,
                                cursor: editable ? "pointer" : "default",
                                background: has ? "var(--marque-paid-bg)" : "var(--marque-canvas)",
                                color: has ? "var(--marque-paid-text)" : "var(--marque-text-muted)",
                                opacity: busy === key ? 0.5 : 1,
                                transition: "background 0.2s ease, color 0.2s ease",
                              }}
                            >
                              {has ? "✓" : "·"}
                            </button>
                          </td>
                        )
                      })}
                    </tr>
                  ))}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

/* ---------- AGENTS TAB (métriques réelles) ---------- */
function AgentsTab({ apiUrl, backendToken }: { apiUrl: string; backendToken: string }) {
  const AGENTS = [
    { key: "agent1", name: nomExpert("agent1"), desc: "Chantiers, clients, dossiers, mails et documents.", tier: "Palier LIGHT / STANDARD" },
    { key: "agent2", name: nomExpert("agent2"), desc: "Analyse de DCE, métrés, pré-chiffrage.", tier: "Palier COMPLEX (vision)" },
    { key: "agent3", name: nomExpert("agent3"), desc: "Consignes retenues, connaissances acquises, compétences.", tier: "Palier COMPLEX" },
  ]
  const [stats, setStats] = useState<Record<string, any>>({})
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    fetch(`${apiUrl}/api/dashboard/agents-activity`, { headers: { Authorization: `Bearer ${backendToken}` } })
      .then((r) => (r.ok ? r.json() : []))
      .then((rows: any[]) => {
        const m: Record<string, any> = {}
        for (const row of rows || []) m[row.agent_id] = row
        setStats(m)
      })
      .catch(() => {})
      .finally(() => setLoaded(true))
  }, [apiUrl, backendToken])

  const metric = (label: string, value: any) => (
    <div>
      <div style={{ fontSize: 11, color: "var(--marque-text-muted)", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em" }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 800, color: "var(--marque-text-primary)" }}>{value}</div>
    </div>
  )

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div className="sym-in" style={{ fontSize: 12, color: "var(--marque-text-muted)" }}>
        Métriques réelles du jour, source <code style={{ fontFamily: "monospace", background: "var(--marque-canvas)", padding: "1px 5px", borderRadius: 4 }}>audit_log</code>.
      </div>
      {AGENTS.map((agent, i) => {
        const s = stats[agent.key] || {}
        const dur = s.avg_duration_ms != null ? `${s.avg_duration_ms} ms` : "n/a"
        return (
          <div key={agent.key} className={`sym-card sym-in sym-in-${i + 1}`} style={{ background: "var(--marque-surface)", borderRadius: "var(--marque-radius-card)", padding: 24, boxShadow: "var(--marque-shadow-card)", border: "1.5px solid var(--marque-border)" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 6 }}>
              <div style={{ width: 40, height: 40, borderRadius: "var(--marque-radius-icon)", background: "linear-gradient(180deg, var(--marque-primary), var(--marque-primary-hover))", boxShadow: "var(--marque-shadow-card)" }} />
              <div>
                <div style={{ fontSize: 15, fontWeight: 700, color: "var(--marque-text-primary)" }}>{agent.name}</div>
                <div style={{ fontSize: 12, color: "var(--marque-text-muted)", marginTop: 1 }}>{agent.tier} · cascade multi-fournisseurs</div>
              </div>
            </div>
            <p style={{ margin: "0 0 14px 52px", fontSize: 13, color: "var(--marque-text-body)", lineHeight: 1.5 }}>{agent.desc}</p>
            <div style={{ display: "flex", gap: 28, marginLeft: 52 }}>
              {metric("Req. aujourd'hui", loaded ? (s.request_count ?? 0) : "…")}
              {metric("Succès", loaded ? (s.success_count ?? 0) : "…")}
              {metric("Échecs", loaded ? (s.failure_count ?? 0) : "…")}
              {metric("Durée moy.", loaded ? dur : "…")}
            </div>
          </div>
        )
      })}
    </div>
  )
}

/* ---------- QUOTAS TAB (super_admin uniquement) ---------- */
function QuotasTab({ backendToken, apiUrl }: { backendToken: string; apiUrl: string }) {
  const [quotas, setQuotas] = useState<Record<string, number | null>>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState("")
  const [success, setSuccess] = useState(false)

  useEffect(() => {
    fetch(`${apiUrl}/api/settings/quotas`, {
      headers: { Authorization: `Bearer ${backendToken}` },
    })
      .then((r) => r.json())
      .then(setQuotas)
      .catch(() => setError("Erreur de chargement"))
      .finally(() => setLoading(false))
  }, [apiUrl, backendToken])

  async function save() {
    setSaving(true); setError(""); setSuccess(false)
    try {
      const res = await fetch(`${apiUrl}/api/settings/quotas`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${backendToken}` },
        body: JSON.stringify({ quotas }),
      })
      if (!res.ok) { setError("Erreur de sauvegarde"); return }
      const updated = await res.json()
      setQuotas(updated)
      setSuccess(true)
      setTimeout(() => setSuccess(false), 2500)
    } catch { setError("Erreur réseau") } finally { setSaving(false) }
  }

  const ROLE_ORDER = ["super_admin", "direction", "commercial", "bureau_etudes", "conducteur", "administratif", "terrain"]

  return (
    <div>
      <div className="sym-card sym-in" style={{ background: "var(--marque-surface)", borderRadius: "var(--marque-radius-card)", boxShadow: "var(--marque-shadow-card)", overflow: "hidden" }}>
        <div style={{ padding: "16px 24px", borderBottom: "1px solid var(--marque-border)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div>
            <div style={{ fontSize: 11, fontWeight: 600, color: "var(--marque-text-muted)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 2 }}>Facturation</div>
            <div style={{ fontSize: 15, fontWeight: 700, color: "var(--marque-text-primary)" }}>Quotas mensuels par rôle</div>
            <div style={{ fontSize: 12, color: "var(--marque-text-muted)", marginTop: 2 }}>
              Nombre max de requêtes / mois. Illimité = aucune restriction.
            </div>
          </div>
          <button onClick={save} disabled={saving || loading} className="sym-tap" style={{
            background: success ? "var(--marque-paid-text)" : "var(--marque-primary)",
            color: "var(--marque-text-on-dark)", border: "none",
            borderRadius: "var(--marque-radius-pill)", padding: "9px 22px", fontSize: 13, fontWeight: 600,
            cursor: saving ? "not-allowed" : "pointer", opacity: saving ? 0.7 : 1,
            transition: "background 0.3s",
          }}>
            {saving ? "Sauvegarde..." : success ? "✓ Sauvegardé" : "Sauvegarder"}
          </button>
        </div>

        {loading ? (
          <div style={{ padding: 24, display: "flex", flexDirection: "column", gap: 10 }}>
            {[0, 1, 2, 3].map((k) => <div key={k} className="sym-skeleton" style={{ height: 52, borderRadius: 12 }} />)}
          </div>
        ) : (
          <div style={{ padding: 24 }}>
            {error && <p style={{ color: "var(--marque-error-text)", fontSize: 13, marginBottom: 16 }}>{error}</p>}
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {ROLE_ORDER.filter((r) => r in quotas).map((role, i) => {
                const limit = quotas[role]
                const isUnlimited = limit === null
                const color = ROLE_COLORS[role] || "#666"
                return (
                  <div key={role} className={`sym-in sym-in-${Math.min(i + 1, 6)}`} style={{
                    display: "flex", alignItems: "center", gap: 16,
                    padding: "14px 18px", borderRadius: 12,
                    border: "1px solid var(--marque-border)", background: "var(--marque-canvas)",
                    transition: "border-color 0.2s ease, box-shadow 0.2s ease",
                  }}>
                    <span style={{
                      background: color + "18", color, padding: "4px 12px",
                      borderRadius: "var(--marque-radius-pill)", fontSize: 12, fontWeight: 700,
                      minWidth: 130, textAlign: "center", display: "inline-block",
                    }}>
                      {ROLE_LABELS[role]}
                    </span>
                    <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, color: "var(--marque-text-body)", cursor: "pointer", userSelect: "none" }}>
                      <input
                        type="checkbox"
                        checked={isUnlimited}
                        onChange={(e) => setQuotas((q) => ({ ...q, [role]: e.target.checked ? null : 100 }))}
                        style={{ width: 16, height: 16, accentColor: "var(--marque-primary)" }}
                      />
                      Illimité
                    </label>
                    {!isUnlimited ? (
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <input
                          type="number" min={1} max={10000}
                          value={limit ?? ""}
                          onChange={(e) => setQuotas((q) => ({ ...q, [role]: parseInt(e.target.value) || 1 }))}
                          style={{
                            padding: "8px 12px", border: "1.5px solid var(--marque-border)",
                            borderRadius: 10, fontSize: 14, width: 110,
                            color: "var(--marque-text-primary)", background: "var(--marque-surface)", outline: "none",
                          }}
                        />
                        <span style={{ fontSize: 13, color: "var(--marque-text-muted)" }}>req / mois</span>
                      </div>
                    ) : (
                      <span style={{ fontSize: 13, color: "var(--marque-text-muted)", fontStyle: "italic" }}>
                        ∞ (aucune restriction)
                      </span>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

/* ---------- SERVICES TAB (état réel via /system) ---------- */
function ServicesTab({ apiUrl, backendToken }: { apiUrl: string; backendToken: string }) {
  const [sys, setSys] = useState<any>(null)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    fetch(`${apiUrl}/api/dashboard/system`, { headers: { Authorization: `Bearer ${backendToken}` } })
      .then((r) => (r.ok ? r.json() : null))
      .then(setSys)
      .catch(() => {})
      .finally(() => setLoaded(true))
  }, [apiUrl, backendToken])

  const p = sys?.providers || {}
  const db = sys?.db || {}
  const services = [
    { name: "PostgreSQL + pgvector", desc: "Base de données + checkpointer LangGraph", up: sys?.checkpointer === "AsyncPostgresSaver", detail: sys ? `${sys.checkpointer} · ${db.threads ?? 0} threads · ${db.users_actifs ?? 0} users` : "non disponible" },
    { name: "Langfuse", desc: "Observabilité LLM (traces)", up: !!sys?.observability?.langfuse_enabled, detail: sys?.observability?.host || "non configuré" },
    { name: "Groq", desc: "LLM gratuit (paliers LIGHT/STANDARD)", up: !!p.groq, detail: p.groq ? "clé configurée" : "clé absente" },
    { name: "OpenRouter", desc: "LongCat / DeepSeek / modèles free", up: !!p.openrouter, detail: p.openrouter ? "clé configurée" : "clé absente" },
    { name: "DeepSeek (API directe)", desc: "deepseek-v4-pro (fallback qualité)", up: !!p.deepseek, detail: p.deepseek ? "clé configurée" : "clé absente" },
    { name: "LongCat (API directe)", desc: "modèle principal", up: !!p.longcat, detail: p.longcat ? "clé configurée" : "clé absente" },
    { name: "Anthropic", desc: "vision agent 2 (palier COMPLEX)", up: !!p.anthropic, detail: p.anthropic ? "clé configurée" : "placeholder / absente" },
    { name: "Ollama (local)", desc: "LLM local (dernier recours)", up: !!p.ollama, detail: "local" },
  ]

  return (
    <div>
      {loaded && !sys && (
        <div style={{ color: "var(--marque-error-text)", fontSize: 13, marginBottom: 12 }}>
          État système indisponible (réservé au super admin).
        </div>
      )}
      <div className="sym-grid-1" style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 14 }}>
        {services.map((s, i) => (
          <div key={i} className={`sym-card sym-in sym-in-${Math.min(i + 1, 6)}`} style={{
            background: "var(--marque-surface)", borderRadius: "var(--marque-radius-card-sm)", padding: 18, boxShadow: "var(--marque-shadow-card)",
            borderLeft: `3px solid ${s.up ? "var(--marque-primary-mid)" : "var(--marque-pending-text)"}`,
          }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
              <div style={{ fontSize: 14, fontWeight: 700, color: "var(--marque-text-primary)" }}>{s.name}</div>
              <span className={loaded ? "sym-pop" : ""} style={{
                fontSize: 11, fontWeight: 700, padding: "3px 10px", borderRadius: "var(--marque-radius-pill)",
                color: s.up ? "var(--marque-paid-text)" : "var(--marque-pending-text)",
                background: s.up ? "var(--marque-paid-bg)" : "var(--marque-pending-bg)",
              }}>
                {!loaded ? "…" : s.up ? "✓ Actif" : "! Inactif"}
              </span>
            </div>
            <div style={{ fontSize: 12, color: "var(--marque-text-muted)", marginBottom: 6 }}>{s.desc}</div>
            <div style={{ fontSize: 11, color: "var(--marque-text-body)", fontFamily: "monospace", background: "var(--marque-canvas)", padding: "4px 8px", borderRadius: 6, display: "inline-block" }}>
              {s.detail}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

/* ---------- MAIN COMPONENT ---------- */
export default function SettingsClient({ initialUsers, backendToken: tokenInitial, currentRole, apiUrl }: Props) {
  const { data: session } = useSession()
  const backendToken = (session as any)?.backendToken || tokenInitial
  // CE QUE MON RÔLE A LE DROIT DE FAIRE (14/09) : une permission cochée dans
  // la matrice ouvre son onglet, sans quoi la case ne servait à rien.
  const [mesPermissions, setMesPermissions] = useState<string[]>([])
  useEffect(() => {
    fetch(`${apiUrl}/api/settings/mes-permissions`, { headers: { Authorization: `Bearer ${backendToken}` }, cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => setMesPermissions(Array.isArray(j?.permissions) ? j.permissions : []))
      .catch(() => setMesPermissions([]))
  }, [apiUrl, backendToken])
  const subTabs = ALL_SUB_TABS.filter((t) => !t.roles || t.roles.includes(currentRole)
    || (t.permission !== undefined && mesPermissions.includes(t.permission)))
  // L'onglet d'ouverture : l'administration pour qui la voit (l'habitude), la
  // boîte Google pour tous les autres — c'est leur seul onglet.
  const [activeTab, setActiveTab] = useState<SubTab>(
    subTabs.some((t) => t.key === "utilisateurs") ? "utilisateurs" : (subTabs[0]?.key ?? "code"))
  // AU RETOUR DE GOOGLE, L'ONGLET D'OÙ L'ON EST PARTI (11/09). Relier l'agenda
  // de la boîte de l'entreprise part de « Clés API » ; Google renvoie sur
  // /parametres, qui s'ouvrait sur Utilisateurs — l'issue n'était lue par
  // personne. Posé après le montage : le serveur ne connaît pas la session.
  useEffect(() => {
    try {
      const voulu = sessionStorage.getItem("parametres_retour_google") as SubTab | null
      if (!voulu) return
      sessionStorage.removeItem("parametres_retour_google")
      if (new URLSearchParams(window.location.search).get("google") && subTabs.some((t) => t.key === voulu))
        setActiveTab(voulu)
    } catch { /* stockage indisponible : l'onglet par défaut */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="sym-page" style={{ padding: 32, maxWidth: 1300, margin: "0 auto" }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: "var(--marque-text-muted)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 4 }} className="sym-in">
        Duret & Sols · Administration
      </div>
      <h1 className="sym-in sym-in-1" style={{ margin: "0 0 6px", fontSize: 26, fontWeight: 800, color: "var(--marque-text-primary)", letterSpacing: "-0.5px" }}>
        Paramètres
      </h1>
      <p className="sym-in sym-in-2" style={{ margin: "0 0 28px", fontSize: 14, color: "var(--marque-text-muted)" }}>
        Configuration du système Duret & Sols, accès {ROLE_LABELS[currentRole] || currentRole}
      </p>

      <div className="sym-in sym-in-3 sym-onglets" style={{ display: "flex", gap: 2, marginBottom: 28, background: "var(--marque-surface)", padding: 6, borderRadius: "var(--marque-radius-card-sm)", width: "fit-content", maxWidth: "100%", boxShadow: "var(--marque-shadow-card)" }}>
        {subTabs.map((t) => {
          const active = activeTab === t.key
          return (
            <button key={t.key} onClick={() => setActiveTab(t.key)} className="sym-tap" style={{
              padding: "8px 18px", border: "none", cursor: "pointer",
              borderRadius: 10, fontSize: 14, fontWeight: active ? 700 : 500,
              color: active ? "var(--marque-primary)" : "var(--marque-text-muted)",
              background: active ? "var(--marque-primary-subtle)" : "transparent",
              boxShadow: active ? "inset 0 0 0 1px var(--marque-primary-light)" : "none",
              transition: "all 0.15s", display: "flex", alignItems: "center", gap: 6,
            }}>
              {t.label}
            </button>
          )
        })}
      </div>

      {activeTab === "code" && (
        <div style={{ display: "flex", justifyContent: "flex-start" }}><MonCode jeton={backendToken} /></div>
      )}
      {activeTab === "utilisateurs" && (
        <UsersTab initialUsers={initialUsers} backendToken={backendToken} currentRole={currentRole} apiUrl={apiUrl} />
      )}
      {activeTab === "plages" && <PlagesTab apiUrl={apiUrl} backendToken={backendToken} users={initialUsers} currentRole={currentRole} />}
      {activeTab === "rbac" && <RBACTab apiUrl={apiUrl} backendToken={backendToken} />}
      {activeTab === "agents" && <AgentsTab apiUrl={apiUrl} backendToken={backendToken} />}
      {activeTab === "quotas" && currentRole === "super_admin" && (
        <QuotasTab backendToken={backendToken} apiUrl={apiUrl} />
      )}
      {activeTab === "services" && <ServicesTab apiUrl={apiUrl} backendToken={backendToken} />}
      {activeTab === "import" && <ImportTab apiUrl={apiUrl} backendToken={backendToken} />}
      {activeTab === "synchro" && currentRole === "super_admin" && (
        <>
          <SyncTab apiUrl={apiUrl} backendToken={backendToken} />
          {/* Le niveau d'accès par dossier du NAS (13/09) : ce qui est synchronisé
              et enrichi se range là, et le chat ne montre que ce que le rôle voit. */}
          <TriNas apiUrl={apiUrl} backendToken={backendToken} />
          <NiveauxNas apiUrl={apiUrl} backendToken={backendToken} />
        </>
      )}
      {activeTab === "cles" && currentRole === "super_admin" && (
        <ClesApiTab apiUrl={apiUrl} backendToken={backendToken} />
      )}
    </div>
  )
}

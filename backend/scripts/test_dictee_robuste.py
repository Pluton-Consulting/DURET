"""
Banc de LA DICTÉE QU'ON PEUT TOUJOURS ARRÊTER, ET QUI NE PERD PAS SON DÉBUT (22/09, Duret).

Relevé de Noa : « il y a un problème de micro sur Duret ». Lu sur le serveur le 22/09 :
  · à 15 h 29 une dictée ILLISIBLE pour les trois moteurs (Groq « is it a valid media
    file? », Whisper « Invalid data », Google « invalid argument ») : deux envois de son
    avaient été abandonnés en route (499 chez nginx), et le navigateur, qui comptait un
    morceau comme parti dès l'envoi, ne le renvoyait jamais. Sans son premier morceau
    (l'en-tête du fichier), le son ne se lit plus ;
  · une autre dictée a tourné PLUS DE DOUZE MINUTES, micro ouvert, sans que personne la
    voie : arrêtée pendant que le micro s'ouvrait, elle démarrait quand même, et, marquée
    arrêtée, plus rien ne pouvait la couper (ni le bouton, ni l'envoi du message, ni la
    borne des dix minutes).

CE QUE CE BANC PROUVE :
  1. le VRAI frontend/lib/dictee.ts, EXÉCUTÉ par Node avec un faux micro et un faux
     serveur : arrêtée pendant l'ouverture, la dictée n'enregistre rien et referme le
     micro ; un envoi perdu repart au tour suivant avec son point de départ ; un 409 fait
     repartir du point où en est le serveur ; un 410 arrête pour de bon, sans dernier
     envoi ; la borne des dix minutes arrête vraiment ; le dernier envoi réessaie ;
  2. le VRAI backend/voix/transcription.py : ce que le serveur a déjà est ignoré, ce qui
     lui manque est réclamé (et le tampon est gardé, même au dernier morceau) ; au-delà
     de onze minutes ou de 12 Mo la dictée est close et aucun moteur n'est plus appelé,
     même si l'onglet continue d'envoyer ;
  3. la route transmet `debut` et répond 409 / 410.
Tombe sur la version d'avant (enregistreur créé après l'arrêt, `debut` absent).

Usage : python backend/scripts/test_dictee_robuste.py [backend]
"""
import asyncio
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import time
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
FRONTEND = BACKEND.parent / "frontend"
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {str(detail)[:400]}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


# ── 1. LE NAVIGATEUR ─────────────────────────────────────────────────────────
SCENARIOS = r"""
import * as D from "%s";
const vraiSetTimeout = globalThis.setTimeout;
const sortie: any = {};
let tic: any = null, butoir: any = null, horlogeArretee = false;
(globalThis as any).setInterval = (fn: any) => { tic = fn; return 1 };
(globalThis as any).clearInterval = () => { horlogeArretee = true };
(globalThis as any).setTimeout = (fn: any, ms: number) => ms >= 600000 ? (butoir = fn, 2) : vraiSetTimeout(fn, 0);
(globalThis as any).clearTimeout = () => {};
const attendre = () => new Promise((r) => vraiSetTimeout(r, 5));
let enregistreurs: any[] = [], pistesArretees = 0, ouvrir: any = null;
class FauxEnregistreur {
  static isTypeSupported() { return true }
  state = "inactive"; mimeType = "audio/webm;codecs=opus"; ondataavailable: any; onstop: any; onerror: any;
  constructor() { enregistreurs.push(this) }
  start() { this.state = "recording" }
  stop() { this.state = "inactive"; this.onstop?.() }
  pousser(n: number) { this.ondataavailable({ data: new Blob([new Uint8Array(n)]) }) }
}
(globalThis as any).window = { isSecureContext: true, MediaRecorder: FauxEnregistreur };
(globalThis as any).MediaRecorder = FauxEnregistreur;
const piste = () => ({ getTracks: () => [{ stop: () => { pistesArretees++ } }] });
let ouvertureLente = false;
Object.defineProperty(globalThis, "navigator", { configurable: true, value: { mediaDevices: {
  getUserMedia: () => ouvertureLente ? new Promise((r) => { ouvrir = r }) : Promise.resolve(piste()) } } });
let envois: any[] = [], reponses: any[] = [];
(globalThis as any).fetch = async (_u: string, init: any) => {
  const b = JSON.parse(init.body);
  envois.push({ debut: b.debut, octets: atob(b.chunk_b64).length, definitif: b.definitif });
  const r = reponses.shift() ?? { statut: 200, corps: { texte: "texte" } };
  if (r === "reseau") throw new TypeError("Failed to fetch");
  return { ok: r.statut < 400, status: r.statut, json: async () => r.corps };
};
function dictee() {
  const etat: any = { erreurs: [], textes: [], fins: 0 };
  const d = D.creerDictee({ apiUrl: "", token: "t", surTexte: (t, def) => etat.textes.push([t, def]),
    surFin: () => { etat.fins++ }, surErreur: (m) => etat.erreurs.push(m) })!;
  return { d, etat };
}

// A. Arrêtée pendant que le micro s'ouvre
ouvertureLente = true;
{ const { d, etat } = dictee();
  const p = d.demarrer(); d.arreter(); ouvrir(piste()); await p; d.arreter();
  sortie.ouverture = { enregistreurs: enregistreurs.length, pistesArretees, envois: envois.length, fins: etat.fins, tic: !!tic }; }
ouvertureLente = false;

// B. Envois repérés : perte, 409, 410
enregistreurs = []; envois = []; pistesArretees = 0; tic = null; horlogeArretee = false;
{ const { d, etat } = dictee();
  await d.demarrer();
  const e = enregistreurs[0];
  e.pousser(100); e.pousser(50); e.pousser(60);
  await tic(); await attendre();                                   // 1er envoi : 0 → 210
  reponses.push("reseau"); e.pousser(40); await tic(); await attendre();   // perdu en route
  sortie.perdu = { erreurs: etat.erreurs.length };
  e.pousser(30); await tic(); await attendre();                    // repart de 210, avec le perdu
  reponses.push({ statut: 409, corps: { detail: { recus: 250, message: "manque" } } });
  e.pousser(20); await tic(); await attendre();                    // le serveur n'en a que 250
  e.pousser(10); await tic(); await attendre();                    // repart de 250
  reponses.push({ statut: 410, corps: { detail: "Cette dictée a dépassé dix minutes." } });
  e.pousser(5); await tic(); await attendre();
  await attendre();
  sortie.envois = envois.map((x) => [x.debut, x.octets, x.definitif]);
  sortie.b = { erreurs: etat.erreurs, fins: etat.fins, etat: e.state, horlogeArretee, pistesArretees }; }

// C. La borne des dix minutes arrête vraiment
enregistreurs = []; envois = []; pistesArretees = 0; butoir = null; horlogeArretee = false;
{ const { d, etat } = dictee();
  await d.demarrer();
  const e = enregistreurs[0];
  e.pousser(100); await tic(); await attendre();
  e.pousser(30);
  butoir(); await attendre(); await attendre();
  sortie.butoir = { etat: e.state, horlogeArretee, pistesArretees, fins: etat.fins,
                    dernier: envois.at(-1) && [envois.at(-1).debut, envois.at(-1).octets, envois.at(-1).definitif] }; }

// D. Le dernier envoi réessaie après un 409
enregistreurs = []; envois = []; butoir = null;
{ const { d, etat } = dictee();
  await d.demarrer();
  const e = enregistreurs[0];
  e.pousser(100); e.pousser(80);
  reponses.push({ statut: 409, corps: { detail: { recus: 0 } } }, { statut: 200, corps: { texte: "phrase entière" } });
  d.arreter(); await attendre(); await attendre(); await attendre();
  sortie.final = { envois: envois.map((x) => [x.debut, x.octets, x.definitif]), textes: etat.textes }; }

console.log(JSON.stringify(sortie));
process.exit(0);
"""

print("1. Le navigateur (lib/dictee.ts exécuté)")
with tempfile.NamedTemporaryFile("w", suffix=".mts", delete=False) as f:
    f.write(SCENARIOS % (FRONTEND / "lib" / "dictee.ts").as_posix())
execution = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", f.name],
                           capture_output=True, text=True, timeout=60)
ligne = (execution.stdout.strip().splitlines() or [""])[-1]
verifier("Node exécute lib/dictee.ts", execution.returncode == 0 and ligne.startswith("{"),
         execution.stderr[-600:] or ligne)
if ligne.startswith("{"):
    s = json.loads(ligne)
    o = s["ouverture"]
    verifier("arrêtée pendant l'ouverture du micro : AUCUN enregistrement ne démarre",
             o["enregistreurs"] == 0 and not o["tic"], o)
    verifier("… et le micro ouvert trop tard est refermé", o["pistesArretees"] == 1, o)
    verifier("… rien n'est envoyé au serveur", o["envois"] == 0, o)
    env = s["envois"]
    verifier("le premier envoi part de l'octet 0", env[:1] == [[0, 210, False]], env)
    verifier("un envoi perdu en route ne se dit pas tout de suite (il repart tout seul)",
             s["perdu"]["erreurs"] == 0, s["perdu"])
    verifier("… il repart au tour suivant, avec son point de départ (210) et le son perdu",
             env[1:3] == [[210, 40, False], [210, 70, False]], env)
    verifier("un 409 (le serveur n'a que 250 octets) fait repartir de 250",
             env[3:5] == [[280, 20, False], [250, 60, False]], env)
    b = s["b"]
    verifier("un 410 arrête l'écoute pour de bon : enregistreur, horloge, micro",
             b["etat"] == "inactive" and b["horlogeArretee"] and b["pistesArretees"] == 1 and b["fins"] == 1, b)
    verifier("… sans dernier envoi, et la raison du serveur est dite",
             not any(x[2] for x in env) and any("dix minutes" in m for m in b["erreurs"]), (env, b["erreurs"]))
    c = s["butoir"]
    verifier("la borne des dix minutes ARRÊTE vraiment (enregistreur, horloge, micro)",
             c["etat"] == "inactive" and c["horlogeArretee"] and c["pistesArretees"] == 1 and c["fins"] == 1, c)
    verifier("… et envoie la fin de la dictée", c["dernier"] == [100, 30, True], c)
    fin = s["final"]
    verifier("le dernier envoi réessaie après un 409, depuis le point du serveur",
             fin["envois"] == [[0, 180, True], [0, 180, True]] and fin["textes"] == [["phrase entière", True]], fin)

# ── 2. LE SERVEUR ────────────────────────────────────────────────────────────
print("2. Le serveur (voix/transcription.py exécuté)")
sys.modules["config"] = types.SimpleNamespace(settings=types.SimpleNamespace(transcription_moteur="local"))
try:
    import httpx  # noqa: F401
except ImportError:
    sys.modules["httpx"] = types.SimpleNamespace(AsyncClient=None, HTTPError=Exception)
spec = importlib.util.spec_from_file_location("transcription_banc", BACKEND / "voix" / "transcription.py")
T = importlib.util.module_from_spec(spec)
spec.loader.exec_module(T)
if not hasattr(T, "MorceauManquant"):
    verifier("voix/transcription.py connaît les envois repérés (`debut`)", False, "MorceauManquant absent")
else:
    APPELS = []

    async def _transcrire(octets, mime="audio/webm", cle_cache="", sans_groq=False):
        APPELS.append(bytes(octets))
        return f"{len(octets)} octets"

    T.moteur_choisi = lambda: "local"
    T.transcrire = _transcrire

    def flux(cle, morceau, debut=None, definitif=False):
        return asyncio.run(T.transcrire_flux(cle, morceau, definitif=definitif, debut=debut))

    A, B, C = b"A" * 100, b"B" * 50, b"C" * 30
    flux("u:1", A, debut=0)
    flux("u:1", B, debut=100)
    r = flux("u:1", B + C, debut=100)                # B renvoyé : déjà reçu
    verifier("ce que le serveur a déjà est ignoré, le reste ajouté", APPELS[-1] == A + B + C and r == "180 octets",
             (len(APPELS[-1]), r))
    for definitif in (False, True):
        try:
            flux("u:1", b"D" * 10, debut=300, definitif=definitif)
            verifier("un trou dans le son est réclamé", False, "aucune exception")
        except T.MorceauManquant as e:
            verifier(f"un trou est réclamé avec le point du serveur ({'dernier' if definitif else 'intermédiaire'})",
                     e.recus == 180, e.recus)
    verifier("… et le tampon est GARDÉ, même au dernier morceau",
             bytes(T._TAMPONS["u:1"]["octets"]) == A + B + C)
    flux("u:1", b"", debut=180, definitif=True)
    verifier("le dernier morceau ferme la dictée", "u:1" not in T._TAMPONS)
    flux("u:2", A)
    flux("u:2", B)
    verifier("un écran d'avant ce correctif (sans `debut`) ajoute comme avant", APPELS[-1] == A + B)

    n = len(APPELS)
    T._TAMPONS["u:2"]["cree"] = time.monotonic() - T.DUREE_MAX_DICTEE_S - 1
    for i in range(3):
        try:
            flux("u:2", C)
            verifier("au-delà de onze minutes la dictée est close", False, "aucune exception")
            break
        except T.DicteeTerminee:
            pass
    verifier("au-delà de onze minutes la dictée est close, et le reste refusé", len(APPELS) == n,
             len(APPELS) - n)
    verifier("… le son est oublié tout de suite", not T._TAMPONS["u:2"]["octets"])
    # Un onglet fantôme envoie toutes les deux secondes : chaque refus doit
    # rafraîchir la marque, sinon elle serait oubliée au bout de dix minutes et
    # la suite du même son repartirait comme une « nouvelle » dictée.
    T._TAMPONS["u:2"]["quand"] = time.monotonic() - T.CACHE_TTL_S + 1
    try:
        flux("u:2", C)
    except T.DicteeTerminee:
        pass
    T._TAMPONS["u:2"]["quand"] -= 2                  # deux secondes plus tard, l'envoi suivant
    try:
        flux("u:2", C)
        rouvert = True
    except T.DicteeTerminee:
        rouvert = False
    verifier("… et la marque tient tant que l'onglet envoie (pas de « nouvelle » dictée sur la suite)",
             not rouvert and len(APPELS) == n, (rouvert, T._TAMPONS.get("u:2")))
    plafond = T.MAX_OCTETS
    T.MAX_OCTETS = 150
    try:
        flux("u:3", A, debut=0)
        flux("u:3", A, debut=100)
        verifier("au-delà de 12 Mo la dictée est close", False, "aucune exception")
    except T.DicteeTerminee:
        verifier("au-delà de 12 Mo la dictée est close", True)
    T.MAX_OCTETS = plafond

# ── 3. LA ROUTE ──────────────────────────────────────────────────────────────
print("3. La route")
chat = (BACKEND / "routers" / "chat.py").read_text(encoding="utf-8")
verifier("la requête porte `debut`", "debut: Optional[int] = None" in chat)
verifier("la route transmet `debut` au flux", "definitif=body.definitif, debut=body.debut" in chat)
verifier("un trou répond 409 avec le point du serveur",
         "HTTP_409_CONFLICT" in chat and '"recus": e.recus' in chat)
verifier("une dictée close répond 410", "except DicteeTerminee as e:" in chat and "HTTP_410_GONE" in chat)

print()
if echecs:
    print(f"✗ {len(echecs)} échec(s)")
    sys.exit(1)
print("✓ 0 échec")

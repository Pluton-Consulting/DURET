"""
Banc du SONDAGE QUI S'ARRÊTE SUR UN JETON MORT (22/09, Duret).

Relevé sur le serveur : plus de 7 000 requêtes refusées (401) en 2 h 40 — un onglet
resté ouvert sur un poste dont la session avait expiré relisait le suivi des
rédactions toutes les 3 s et l'état de la file toutes les 4 s, pour toujours.

CE QUE CE BANC PROUVE :
  · `reprendreSession` (lib/session.ts) EXÉCUTÉ par Node avec un faux fetch : une
    seule reprise pour tout l'écran, quel que soit le nombre d'appelants ; un jeton
    frais recharge la page UNE fois ; une session fermée ne recharge rien ;
  · SuiviRedactions : un 401 ne reprogramme pas le sondage ;
  · ChatWindow : un 401 du sondage de la file le coupe, les ticks suivants ne
    partent plus.
Tombe sur la version d'avant (`reprendreSession` absent).

Usage : python backend/scripts/test_sondage_session.py [backend|frontend]
"""
import json
import pathlib
import re
import subprocess
import sys
import tempfile

# La recette passe le chemin du BACKEND ; à la main, on peut donner celui du frontend.
_arg = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "frontend").resolve()
front = _arg if (_arg / "lib" / "session.ts").exists() else _arg.parent / "frontend"
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {str(detail)[:300]}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def executer(code: str):
    with tempfile.NamedTemporaryFile("w", suffix=".mts", delete=False) as f:
        f.write(code)
    sortie = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", f.name],
                            capture_output=True, text=True, timeout=60)
    ligne = (sortie.stdout.strip().splitlines() or [""])[-1]
    return ligne, sortie


session = (front / "lib" / "session.ts").read_text(encoding="utf-8")
suivi = (front / "components" / "chat" / "SuiviRedactions.tsx").read_text(encoding="utf-8")
chat = (front / "components" / "chat" / "ChatWindow.tsx").read_text(encoding="utf-8")
module = (front / "lib" / "session.ts").as_posix()

print("1. reprendreSession, exécuté")
if "export function reprendreSession" not in session:
    verifier("lib/session.ts exporte `reprendreSession`", False, "absent")
else:
    ligne, sortie = executer(r"""
import * as S from "%s";
let rechargements = 0, appels = 0;
globalThis.window = { location: { reload: () => { rechargements++ } } };
globalThis.fetch = async () => { appels++; return { ok: true, json: async () => ({ backendToken: "jwt-frais" }) } };
const r = await Promise.all([S.reprendreSession(), S.reprendreSession(), S.reprendreSession()]);
console.log(JSON.stringify({ r, rechargements, appels, expire: S.estSessionExpiree({ status: 401 }), autre: S.estSessionExpiree({ status: 500 }) }));
""" % module)
    verifier("Node exécute lib/session.ts", sortie.returncode == 0 and ligne.startswith("{"), sortie.stderr[-400:])
    if ligne.startswith("{"):
        d = json.loads(ligne)
        verifier("trois sondages refusés → UNE seule interrogation de la session", d["appels"] == 1, d)
        verifier("jeton frais → la page se recharge UNE fois", d["rechargements"] == 1 and d["r"] == [True] * 3, d)
        verifier("401 reconnu, 500 non", d["expire"] is True and d["autre"] is False, d)

    ligne, sortie = executer(r"""
import * as S from "%s";
let rechargements = 0;
globalThis.window = { location: { reload: () => { rechargements++ } } };
globalThis.fetch = async () => ({ ok: true, json: async () => ({}) });
const r = await S.reprendreSession();
console.log(JSON.stringify({ r, rechargements }));
""" % module)
    verifier("session vraiment fermée → aucun rechargement", ligne == '{"r":false,"rechargements":0}',
             ligne or sortie.stderr[-300:])

print("2. SuiviRedactions : un 401 ne reprogramme pas le sondage")
verifier("importe estSessionExpiree / reprendreSession",
         re.search(r'import \{[^}]*estSessionExpiree[^}]*reprendreSession[^}]*\} from "@/lib/session"', suivi))
verifier("le 401 coupe le sondage et lance la reprise",
         re.search(r"estSessionExpiree\(e\)\)\s*\{\s*coupe = true;\s*void reprendreSession\(\)", suivi))
verifier("la reprogrammation exige que le sondage ne soit pas coupé",
         "if (actif && !coupe) minuterie = setTimeout(lire, delai)" in suivi)
verifier("plus de reprogrammation sans condition",
         "if (actif) minuterie = setTimeout(lire, delai)" not in suivi)

print("3. ChatWindow : un 401 du sondage de la file le coupe")
verifier("le sondage ne part plus une fois coupé",
         "if (!token || sondageCoupeRef.current) return" in chat)
verifier("le 401 coupe et lance la reprise",
         re.search(r"estSessionExpiree\(e\)\)\s*\{\s*sondageCoupeRef\.current = true;\s*void reprendreSession\(\)", chat))

print()
if echecs:
    print(f"✗ {len(echecs)} échec(s)")
    sys.exit(1)
print("✓ 0 échec")

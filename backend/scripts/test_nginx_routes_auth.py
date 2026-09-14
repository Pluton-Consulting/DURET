"""
Banc « CHAQUE ROUTE /api/auth/ ARRIVE CHEZ CELUI QUI LA PORTE » (14/09).

Relevé de Noa (Duret) : la page des cartes disait « Le serveur ne répond pas
pour le moment. Réessayez dans un instant. » alors que le backend répondait.
Constaté en prod : `GET /api/auth/connexion/profils` rendait un 400
« Bad request. » avec l'en-tête `vary: rsc, next-router-state-tree…` — c'était
NextAuth qui répondait. nginx ne routait vers le backend que `magic-link/` et
`logout` sous `/api/auth/` ; tout le reste partait au frontend. Les appels du
serveur Next (BACKEND_URL) ne passent pas par nginx : seul le navigateur
tombait dans le trou, et aucun banc ne regardait nginx.

CE QUE CE BANC PROUVE : il lit les routes RÉELLES de `routers/auth.py` et les
`location` RÉELLES de `nginx/nginx.conf`, rejoue la règle de sélection de
nginx (exacte, puis préfixe le plus long, puis expressions dans l'ordre,
`^~` compris), et exige que chaque route du backend aille au backend et que
chaque route de NextAuth reste au frontend. Tombe sur la version d'avant.
"""
import pathlib
import re
import sys

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
NGINX = BACKEND.parent / "nginx" / "nginx.conf"
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def locations(texte):
    """(modificateur, motif, cible) de chaque bloc location du serveur."""
    sortie = []
    for m in re.finditer(r"^\s*location\s+(=|~\*|~|\^~)?\s*(\S+)\s*\{(.*?)^\s*\}", texte, re.M | re.S):
        cible = re.search(r"proxy_pass\s+http://\$(\w+)", m.group(3))
        sortie.append((m.group(1) or "", m.group(2), cible.group(1) if cible else None))
    return sortie


def choisir(locs, chemin):
    """La règle de nginx : `=` exact gagne ; sinon le préfixe le plus long ;
    s'il porte `^~`, il gagne ; sinon la première expression qui correspond ;
    sinon le préfixe le plus long."""
    for mod, motif, cible in locs:
        if mod == "=" and chemin == motif:
            return cible
    prefixes = [(motif, mod, cible) for mod, motif, cible in locs
                if mod in ("", "^~") and chemin.startswith(motif)]
    meilleur = max(prefixes, key=lambda p: len(p[0]), default=None)
    if meilleur and meilleur[1] == "^~":
        return meilleur[2]
    for mod, motif, cible in locs:
        if mod in ("~", "~*") and re.search(motif, chemin, re.I if mod == "~*" else 0):
            return cible
    return meilleur[2] if meilleur else None


print("Routes /api/auth/ ↔ nginx")
texte = NGINX.read_text()
locs = locations(texte)
verifier("nginx.conf porte des blocs location", len(locs) > 5, str(len(locs)))

routes = re.findall(r'@router\.(?:get|post|put|delete|patch)\("([^"]+)"', (BACKEND / "routers" / "auth.py").read_text())
verifier("routers/auth.py porte des routes", len(routes) > 3, str(routes))
for r in routes:
    chemin = "/api/auth" + re.sub(r"\{[^}]+\}", "abc123", r)
    cible = choisir(locs, chemin)
    verifier(f"{chemin} → backend", cible == "cible_backend", f"part vers {cible}")

# Ce que NextAuth sert lui-même : ne doit jamais partir au backend.
for na in ("session", "csrf", "providers", "signin", "signin/credentials",
           "callback/credentials", "signout", "error", "_log"):
    chemin = f"/api/auth/{na}"
    verifier(f"{chemin} → frontend (NextAuth)", choisir(locs, chemin) == "cible_frontend",
             f"part vers {choisir(locs, chemin)}")

# Le reste de l'API et le WebSocket gardent leur chemin.
verifier("/api/chat/ws/x → backend", choisir(locs, "/api/chat/ws/x") == "cible_backend")
verifier("/api/settings/modeles → backend", choisir(locs, "/api/settings/modeles") == "cible_backend")
verifier("/login → frontend", choisir(locs, "/login") == "cible_frontend")
# Un nom qui commence pareil sans être la route ne doit pas être happé.
verifier("/api/auth/profilsX n'est pas happé", choisir(locs, "/api/auth/profilsX") == "cible_frontend")

print(f"\n{'ÉCHEC' if echecs else 'OK'} — {len(echecs)} échec(s)")
sys.exit(1 if echecs else 0)

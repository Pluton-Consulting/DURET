# Déployer un projet (Symbiose, Duret…) sur un VPS Ubuntu — VPN Headscale + HTTP

Runbook **générique** pour déployer n'importe quel projet basé sur cette stack
(**FastAPI + Next.js + Postgres/pgvector + browser-worker + nginx**, orchestrés par
Docker Compose) sur un VPS Ubuntu. Accès **privé via VPN auto-hébergé (Headscale)**, en
**HTTP** : le tunnel VPN (WireGuard) chiffre déjà tout → **pas de certificat à gérer**.

> **Remplace partout les `<…>` par tes valeurs :**
>
> | Placeholder | Rôle | Ex. Symbiose | Ex. Duret |
> |---|---|---|---|
> | `<REPO>` | dépôt GitHub | `BenITNoaBenitez/SYMBIOSE` | `BenITNoaBenitez/DURET-SOLS` |
> | `<DOSSIER>` | sous-dossier contenant `docker-compose.yml` | `symbiose-noa` | `duret-sols` |
> | `<DOMAINE>` | ton domaine (accès DNS requis) | `pluton-consulting.fr` | `ton-domaine.fr` |
> | `<APP>` | sous-domaine de l'appli | `symbiose` | `duret` |
> | `<PROJET>` | nom court (user Headscale) | `symbiose` | `duret` |
> | `<DB>` / `<USER>` | base / utilisateur Postgres | `symbiose_noa` / `noa_user` | `duret_sols` / `duret_user` |

> **Deux « admin » à ne pas confondre :** le compte **Linux OVH** (`ubuntu`/`root`, gère la
> machine) ≠ **`FIRST_ADMIN_EMAIL`** (ton login *dans* l'appli, par lien magique).
>
> **Headscale ≠ Tailscale :** **Headscale** = le *serveur* VPN que tu héberges. **`tailscale`**
> = le *client* open-source, pointé sur TON serveur via `--login-server` (jamais le cloud Tailscale).

---

## Architecture (HTTP privé, derrière le VPN)

```
   Postes (client tailscale connecté à TON serveur Headscale)
            │   tunnel WireGuard chiffré (privé, jamais l'Internet public)
            ▼
   http://<APP>.<DOMAINE>   → IP VPN du VPS (100.64.0.x)
            ▼
   nginx (écoute sur HEADSCALE_IP:80)
       ├── /            → frontend:3000
       ├── /api/auth/   → frontend  (NextAuth : session/csrf/callback)
       ├── /api/        → backend:8000
       └── /api/ws/     → backend:8000  (WebSocket)
            │
   frontend · backend · browser-worker · postgres(pgvector)

   ── en parallèle ──  vpn-<APP>.<DOMAINE> → IP PUBLIQUE du VPS → serveur Headscale
```

Deux enregistrements DNS (sous-domaine VPN **unique par projet** si tu réutilises un même
domaine) : **`vpn-<APP>`** → IP **publique** (serveur Headscale) ; **`<APP>`** → IP
**VPN** (l'appli, joignable seulement sur le VPN). Deux IP à garder : **`IP_PUBLIQUE`** (OVH) et
**`VPN_IP`** (`tailscale ip -4`, ex. `100.64.0.1`).

---

## Prérequis
- VPS Ubuntu 22.04/24.04 — **VPS-2 (4 vCPU / 8 Go)** minimum.
- Accès SSH OVH (`ubuntu`/`root`) + IP publique.
- La main sur le **DNS de `<DOMAINE>`** (2 enregistrements A).
- Un **PAT GitHub** (dépôt privé).
- Les **clés API** : Groq, LongCat, Gemini (`GOOGLE_API_KEY`), Resend.

---

## Étape 0 — Se connecter
```bash
ssh ubuntu@IP_PUBLIQUE
```

## Étape 1 — Mettre à jour
```bash
sudo apt update && sudo apt upgrade -y
```

## Étape 2 — Pare-feu
```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp             # Headscale (ACME + coordination, sur l'IP publique)
sudo ufw allow 443/tcp
sudo ufw allow in on tailscale0   # trafic entrant DEPUIS le VPN (l'app)
sudo ufw --force enable && sudo ufw status
```
> ⚠ **Docker publie les ports en contournant UFW.** Pour que l'app reste privée, nginx est lié
> à l'**IP VPN** (`HEADSCALE_IP`, étape 7), pas à `0.0.0.0`. (Les ports internes `3000`/`8000`
> restent techniquement exposés par Docker — surface d'attaque mineure, endpoints protégés par JWT.)

## Étape 3 — Swap (2 Go)
```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

## Étape 4 — Docker
```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
```
**Déconnecte/reconnecte** (`exit` puis `ssh …`), puis `docker --version && docker compose version`.

## Étape 5 — VPN Headscale

**5.1 — DNS :** crée `vpn-<APP>.<DOMAINE>` → **IP_PUBLIQUE**.

**5.2 — Installer :**
```bash
VER=0.29.2   # dernière version : github.com/juanfont/headscale/releases
wget -O headscale.deb "https://github.com/juanfont/headscale/releases/download/v${VER}/headscale_${VER}_linux_amd64.deb"
sudo apt install -y ./headscale.deb
headscale version   # DOIT afficher 0.29.2 (surtout PAS 0.23.x)
```
> ⚠ **N'installe PAS via `apt install headscale`** (le dépôt Ubuntu fournit une **0.23** trop vieille
> → le client tailscale récent ne se connecte pas et `tailscale up` **tourne en boucle**). Toujours le
> `.deb` de la release ci-dessus. Déjà coincé sur une vieille version ? Voir **« Mettre à jour Headscale »** plus bas.

**5.3 — Configurer** — pars du config-example officiel de ta version, puis modifie 4 lignes :
```bash
sudo wget -O /etc/headscale/config.yaml https://raw.githubusercontent.com/juanfont/headscale/v${VER}/config-example.yaml
sudo nano /etc/headscale/config.yaml
```
```yaml
server_url: https://vpn-<APP>.<DOMAINE>
listen_addr: IP_PUBLIQUE:443
tls_letsencrypt_hostname: vpn-<APP>.<DOMAINE>
tls_letsencrypt_listen: IP_PUBLIQUE:80
```
> ⚠ **Garde les `:443` et `:80` après l'IP** (sans port → Headscale crashe en boucle).
```bash
sudo systemctl enable --now headscale
sudo systemctl status headscale --no-pager   # "active (running)"
```

**5.4 — Utilisateur + clé** (⚠ en 0.29, `--user` = l'**ID numérique**) :
```bash
sudo headscale users create <PROJET>
sudo headscale users list                     # note l'ID
sudo headscale preauthkeys create --user <ID> --reusable --expiration 8760h
# → copie la clé "hskey-auth-..." (VPS + postes)
```

**5.5 — Connecter le VPS au VPN :**
```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --login-server https://vpn-<APP>.<DOMAINE> --authkey hskey-auth-...
tailscale ip -4        # → VPN_IP (ex. 100.64.0.1)
```

**5.6 — DNS :** crée `<APP>.<DOMAINE>` → **VPN_IP**.

## Étape 6 — Cloner le projet
```bash
cd ~
git clone https://github.com/<REPO>.git   # login = pseudo, mot de passe = PAT
cd <REPO_DOSSIER>/<DOSSIER>                # le dossier qui contient docker-compose.yml
```
> Repo privé : `git config --global credential.helper store` puis un `git pull` (PAT saisi une fois) évite de retaper le token.

## Étape 7 — Fichier `.env` (HTTP)
Secrets neufs : `openssl rand -hex 32` (×4). Puis `nano .env` :
```ini
# Base
POSTGRES_DB=<DB>
POSTGRES_USER=<USER>
POSTGRES_PASSWORD=⟨secret1⟩
DATABASE_URL=postgresql+asyncpg://<USER>:⟨secret1⟩@postgres:5432/<DB>
# Sécurité
JWT_SECRET_KEY=⟨secret2⟩
NEXTAUTH_SECRET=⟨secret3⟩
INGESTION_WEBHOOK_SECRET=⟨secret4⟩
# URLs (HTTP + ton sous-domaine, identiques les 3)
APP_URL=http://<APP>.<DOMAINE>
NEXTAUTH_URL=http://<APP>.<DOMAINE>
NEXT_PUBLIC_API_URL=http://<APP>.<DOMAINE>
# Réseau : nginx écoute sur l'IP VPN (= tailscale ip -4)
HEADSCALE_IP=<VPN_IP>
# Clés API
GROQ_API_KEY=…
LONGCAT_API_KEY=…
LONGCAT_BASE_URL=https://api.longcat.chat/openai
GOOGLE_API_KEY=…
RESEND_API_KEY=…
RESEND_FROM_EMAIL=noreply@<domaine-vérifié-dans-Resend>
ANTHROPIC_API_KEY=placeholder
# Admin de l'appli (login lien magique)
FIRST_ADMIN_EMAIL=ton.email@exemple.fr
```
> ⚠ **`NEXT_PUBLIC_API_URL` est gelée au BUILD** du frontend → mets-la correcte **avant**
> `./deploy.sh`. La changer plus tard ⇒ rebuild.
> ⚠ Ne définis PAS `HEADSCALE_IP` dans ton shell (`export`) — ça écraserait le `.env` et nginx
> se lierait au mauvais endroit. En cas de doute : `unset HEADSCALE_IP` avant de déployer.

## Étape 8 — Déployer
```bash
chmod +x deploy.sh
./deploy.sh
```
Le script : build (frontend avec la bonne URL) → démarrage → **migrations suivies** (ne rejoue
que les nouvelles) → super_admin `FIRST_ADMIN_EMAIL` → skills → **redémarre nginx** (re-résout
les IP, évite les 502). `docker compose ps` doit montrer tout en `running`/`healthy`.

## Étape 9 — Accès
Sur chaque **poste** : installer le client tailscale, puis
`tailscale up --login-server https://vpn-<APP>.<DOMAINE> --authkey hskey-auth-...` → ouvrir
**`http://<APP>.<DOMAINE>`** → écran de connexion → email → lien magique → connecté.
> Si le poste utilise déjà **Tailscale officiel** ailleurs, il bascule entre les deux réseaux avec
> `tailscale up --login-server … --force-reauth` (un client = un réseau à la fois).

## Étape 10 — Maintenance
```bash
# Mise à jour :
cd ~/<REPO_DOSSIER>/<DOSSIER> && git pull && ./deploy.sh
# Sauvegarde (cron quotidien) :
./backup.sh          # dump base + .env, dans ~/…-backups (voir backup.sh)
```

---

## Mettre à jour Headscale (si bloqué sur une vieille version)

Symptôme : `tailscale up` **tourne en rond** et `headscale version` affiche une **0.23.x**. Le format
de config **et** le schéma de base ont changé depuis → on réinstalle proprement (base neuve).

```bash
sudo systemctl stop headscale
VER=0.29.2
wget -O /tmp/headscale.deb "https://github.com/juanfont/headscale/releases/download/v${VER}/headscale_${VER}_linux_amd64.deb"
sudo apt install -y /tmp/headscale.deb
headscale version                              # doit afficher 0.29.2

# config : repartir de l'exemple 0.29 (format changé), recopier tes 4 lignes depuis la sauvegarde
sudo cp /etc/headscale/config.yaml /etc/headscale/config.yaml.bak
sudo wget -O /etc/headscale/config.yaml "https://raw.githubusercontent.com/juanfont/headscale/v${VER}/config-example.yaml"
sudo nano /etc/headscale/config.yaml           # server_url · listen_addr:443 · tls_letsencrypt_hostname · tls_letsencrypt_listen:80

# base neuve (schéma incompatible avec la 0.23) — l'ancienne est sauvegardée
sudo mv /var/lib/headscale/db.sqlite /var/lib/headscale/db.sqlite.bak 2>/dev/null || true

sudo systemctl restart headscale
sudo systemctl status headscale --no-pager     # "active (running)"

# base neuve → recréer user + clé (⚠ en 0.29, --user = l'ID numérique de « users list »)
sudo headscale users create <PROJET>
sudo headscale users list
sudo headscale preauthkeys create --user <ID> --reusable --expiration 8760h
```
> Base neuve ⇒ **chaque machine doit se reconnecter** :
> `tailscale up --login-server https://vpn-<APP>.<DOMAINE> --authkey hskey-auth-…`.

---

## Pièges rencontrés (retours d'expérience)
- **Headscale 0.23 trop vieux** pour les clients tailscale récents → `tailscale up` **tourne en boucle**. Vérifie `headscale version` ; installe/mets à jour en **0.29+** (voir « Mettre à jour Headscale »). ⚠ `apt install headscale` fournit une 0.23 — à éviter.
- **`--user`** attend l'**ID numérique** en 0.29 (pas le nom).
- **`server_url` doit être en `https://`** (Headscale) même si l'app est en HTTP.
- **`.env` collé en double** → `deploy.sh` gère (1re occurrence), mais évite.
- **502 après un déploiement** = nginx pointe sur une ancienne IP → `docker compose … restart nginx` (fait auto par `deploy.sh`).
- **Onglets vides / 502** = backend joignable ? `docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail=60 backend`.
- **Frontend « clientModules » au build** = bug Next 14.2 standalone + groupes de routes → le `Dockerfile` recopie `.next/server` (déjà géré).

> **Besoin du HTTPS ?** Voir « Étape 11 » ci-dessous. Le tunnel VPN chiffre déjà tout, donc
> le HTTP suffit pour la confidentialité, mais Google et Microsoft **refusent une URL de
> redirection en `http://`** : le HTTPS devient obligatoire dès qu'on veut une connexion
> par compte Google ou Microsoft.

---

## Étape 11 — Passer en HTTPS (optionnel)

**Ce que ça change :** un vrai cadenas, un certificat public valide, et la possibilité
d'utiliser OAuth (Google, Microsoft). **Ce que ça ne change pas :** l'application reste sur
l'IP privée du VPN, injoignable depuis internet. Caddy ne fait que des connexions
**sortantes** (Let's Encrypt et l'API DNS) ; aucun port n'est ouvert en plus côté public.

Le certificat est obtenu par **challenge DNS-01**, seule méthode possible ici : l'enregistrement
A de l'application pointe vers une IP privée (`100.64.x.x`), que Let's Encrypt ne peut pas
joindre. Les challenges HTTP-01 et TLS-ALPN-01 sont donc exclus, pas seulement déconseillés.

### 11.1 — Choisir le nom, et vérifier son DNS

L'image Caddy est compilée avec le module **Gandi** (`caddy/Dockerfile`). Le nom choisi doit
donc être dans une zone hébergée chez Gandi. Vérifier avant tout :

```bash
nslookup -type=NS <DOMAINE>
```

- serveurs `*.gandi.net` → rien à faire ;
- serveurs `*.ovh.net` ou autres → remplacer `caddy-dns/gandi` par le module correspondant
  dans `caddy/Dockerfile` (`caddy-dns/ovh`, `caddy-dns/cloudflare`…) et adapter la directive
  `dns …` du `Caddyfile`.

### 11.2 — Enregistrement DNS

Un A supplémentaire : **`<APP>`** → **IP VPN** (`tailscale ip -4`, ex. `100.64.0.1`).
C'est le même que celui de l'étape « Architecture » ; s'il existe déjà, rien à faire.

### 11.3 — Jeton Gandi

Un **Personal Access Token** créé sur `admin.gandi.net`, avec le droit de gérer le DNS du
domaine. **Pas** une clé API LiveDNS : le module `caddy-dns/gandi` ne l'accepte plus.

### 11.4 — Compléter `.env`

```ini
# Les trois URL passent en https (identiques)
APP_URL=https://<APP>.<DOMAINE>
NEXTAUTH_URL=https://<APP>.<DOMAINE>
NEXT_PUBLIC_API_URL=https://<APP>.<DOMAINE>

# nginx repasse en INTERNE : sinon lui et Caddy se disputent le port 80 et rien ne démarre
HEADSCALE_IP=127.0.0.1

# Caddy
VPN_IP=<IP VPN>                       # tailscale ip -4
APP_HOSTNAME=<APP>.<DOMAINE>
ACME_EMAIL=<adresse>
GANDI_API_TOKEN=<PAT>
```

> ⚠ `NEXT_PUBLIC_API_URL` est un **argument de construction** : il est figé dans le paquet
> JavaScript envoyé au navigateur. Un simple redémarrage ne suffit pas, il faut **reconstruire**
> l'image du frontend. `deploy.sh` le fait (`--build`), mais un `restart` manuel ne le ferait pas :
> le chat continuerait d'appeler l'ancienne adresse en clair, et le navigateur bloquerait
> l'appel comme contenu mixte.

### 11.5 — Déployer

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.https.yml up -d --build
```

### 11.6 — Vérifier

```bash
docker compose ... logs --tail=40 caddy      # doit montrer « certificate obtained successfully »
curl -I https://<APP>.<DOMAINE>              # depuis un poste du VPN : HTTP/2 200
```

Puis, dans un navigateur du VPN : cadenas fermé, connexion par lien magique, et **le chat qui
streame** (c'est lui qui prouve que le WebSocket est bien passé en `wss://`).

> ⚠ **HSTS.** Le `Caddyfile` pose `Strict-Transport-Security: max-age=31536000`. Une fois
> reçu, le navigateur **refuse de redescendre en clair pendant un an**, et le retour arrière
> devient impossible côté poste. Ne l'active qu'après avoir vérifié que tout répond en HTTPS.
> Pour tester sans s'engager, commenter cette ligne, valider, puis la remettre.

### 11.7 — Revenir en arrière

Relancer sans le troisième fichier, et remettre les trois URL en `http://` plus
`HEADSCALE_IP=<IP VPN>` :

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Sous réserve du HSTS ci-dessus : les postes qui ont déjà reçu l'en-tête refuseront le HTTP.

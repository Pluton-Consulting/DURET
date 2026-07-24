# Duret & Sols — Assistant IA interne

Assistant IA interne de **Duret & Sols** (entreprise BTP — travaux de sols et revêtements).
Multi-agents, mémoire d'entreprise en RAG, **zéro donnée personnelle envoyée aux LLM externes**
(anonymisation avant appel), accès **privé via VPN auto-hébergé**.

## Ce que fait l'assistant
- **Agent Administratif / Suivi de chantiers** : recherche par chantier, suivi commandes / réserves /
  échéances, rapprochement commande‑livraison‑facture, règlements fournisseurs, facturation
  sous‑traitants, dossiers juridiques, brouillons de mails.
- **Agent Appels d'offres / Chiffrage / Plans** : analyse CCTP / CCAP / RC / DPGF, synthèse d'appel
  d'offres, analyse de plans, métrés (surfaces / plinthes), base de pré‑chiffrage
  (**validation humaine obligatoire**).
- Répond en français, cite ses sources, n'invente jamais de donnée (montant, date, référence).
- **Agent navigateur** (browser-use) : navigation web autonome, extraction → RAG, avec
  **validation humaine** obligatoire pour toute action modifiante.
- **RGPD *fail-closed*** : requête et documents masqués (NER spaCy) avant l'appel LLM, puis réhydratés ;
  si l'anonymiseur est indisponible, aucun appel externe n'est fait.
- **Isolation par profil** : RBAC par fonctionnalité + RLS Postgres (conversations/KPI propres à chaque utilisateur).

## Stack
| Couche | Techno |
|---|---|
| Backend | FastAPI · LangGraph / LangChain · cascade LLM (OpenRouter → Groq → Ollama) · tracing Langfuse |
| Frontend | Next.js 14 (App Router, standalone) · NextAuth v5 (lien magique) |
| Données | PostgreSQL + **pgvector** (RAG) · Row Level Security |
| Agent navigateur | `browser-worker` (browser-use) + file de validation humaine (HITL) |
| Infra | Docker Compose · nginx · **VPN Headscale auto-hébergé** (app en HTTP derrière le tunnel) |

## Structure du dépôt
```
.
├── backend/                 # FastAPI · agents LangGraph · RAG · sécurité (RBAC/RLS/anonymisation)
├── frontend/                # Next.js 14 + NextAuth (thème bleu Duret & Sols)
├── browser-worker/          # agent navigateur (browser-use) + HITL
├── nginx/                   # reverse proxy
├── docker-compose*.yml      # base · prod · dev · langfuse
├── deploy.sh                # déploiement (build + migrations suivies + super_admin + restart nginx)
├── backup.sh                # sauvegarde base + .env (rétention 14 j)
├── DEPLOY.md                # runbook VPS générique (VPN Headscale + HTTP)
├── SETUP.md                 # mise en route détaillée
├── README-DURET.md          # note d'indépendance + réorientation métier BTP
└── .env.example             # gabarit de configuration
```

## Démarrage rapide
```bash
cp .env.example .env          # renseigner les valeurs (secrets, clés API, URLs)
docker compose up -d --build
```
- **Déploiement sur un VPS** (VPN + HTTP) : voir [`DEPLOY.md`](DEPLOY.md).
- **Mise en route détaillée** : voir [`SETUP.md`](SETUP.md).
- **Spécificités Duret & Sols** (indépendance, réorientation BTP, connecteurs) : voir [`README-DURET.md`](README-DURET.md).

## Branches
- **`main`** → production (le VPS suit cette branche).

## Sécurité
- **Secrets hors dépôt** : `.env`, `prod.env`, `backend/secrets/` sont **gitignorés** — ne jamais committer de clé.
  Chaque déploiement dépose son propre `.env` sur le VPS (cf. `DEPLOY.md`).
- **Aucune PII vers les LLM externes** (anonymisation NER *fail-closed*).
- **Accès privé** : l'application n'est jamais exposée sur l'Internet public — servie en **HTTP derrière le VPN**
  (tunnel WireGuard chiffré via Headscale).

---
Développé par **Pluton Consulting** pour Duret & Sols.

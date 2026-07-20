# Duret & Sols — Infrastructure IA métier (BTP)

Copie **100 % indépendante** de la plateforme, réorientée pour **Duret & Sols**
(entreprise de travaux de sols et revêtements). Thème **bleu**, secrets **régénérés**,
aucune donnée ni identifiant partagé avec un autre client.

## 1. Ce qui est indépendant
- **Dossier séparé** (`DURET-SOLS/`), sans `.git`, `node_modules`, `.next` ni secrets hérités.
- **Secrets NEUFS** dans `.env` : `POSTGRES_PASSWORD`, `JWT_SECRET_KEY`, `NEXTAUTH_SECRET`,
  `INGESTION_WEBHOOK_SECRET` régénérés aléatoirement (vérifié : aucun secret Duret & Sols présent).
- **Isolation Docker** : `COMPOSE_PROJECT_NAME=duret-sols` → conteneurs et volumes distincts
  (`duret-sols-*`). Base de données `duret_sols` / utilisateur `duret_user`.
- `backend/secrets/site_credentials.json` = `{}` (vide).

> ⚠️ Sur une même machine, Duret & Sols et un autre projet **ne tournent pas en même temps**
> (ports 3000/8000). En pratique Duret & Sols tourne sur **sa propre machine / son VPS**.

## 2. À REMPLIR par le client (aucune clé héritée)
Dans `.env`, renseigner les comptes **propres à Duret & Sols** :
- `GROQ_API_KEY` (LLM rapide, gratuit — console.groq.com)
- `LONGCAT_API_KEY` (LLM qualité/raisonnement)
- `GOOGLE_API_KEY` (embeddings Gemini = base vectorielle — aistudio.google.com/apikey)
- `RESEND_API_KEY` + `RESEND_FROM_EMAIL` (email de connexion « magic link »)
- (optionnel) `OPENROUTER_API_KEY`, `DEEPSEEK_API_KEY`, `ANTHROPIC_API_KEY`, Langfuse.

## 3. Réorientation métier (paysage → BTP)
- **Agent 1 — Administratif / Suivi de chantiers** (Nathalie & Éric) : recherche par chantier,
  suivi commandes / réserves / échéances, rapprochement commande‑livraison‑facture, règlements
  fournisseurs, facturation sous‑traitants, dossiers juridiques, brouillons de mails.
- **Agent 2 — Appels d'offres / Chiffrage / Plans** (Benoît) : analyse CCTP / CCAP / RC / DPGF,
  synthèse d'appel d'offres, analyse de plans, métrés (surfaces / plinthes), coûts SOGED,
  obligations réemploi / réinsertion, base de pré‑chiffrage (**validation Benoît obligatoire**).
- **Catalogue de 25 skills BTP** (`backend/scripts/seed_skills_catalogue.py`) — statut *draft*,
  à valider par la direction dans l'onglet **Skills**.
- Onglets renommés : *Administratif*, *Appels d'offres*. Base documentaire = mémoire centrale.

## 4. Connecteurs (à adapter)
Duret & Sols utilise **Gmail, MyFiteco, Ediflex, Corus, NAS/Drive, Google Agenda**. Les connecteurs
Extrabat/Deytime hérités sont **inactifs** — à remplacer par les outils Duret lors de la phase
« collecte des accès ». Priorité brief : **récupérer les accès + un dossier pilote** (un appel
d'offres complet : CCTP, CCAP, RC, DPGF, plans, devis final) pour lancer les tests.

## 5. Lancer (quand la machine/VPS est prête)
```bash
cd DURET-SOLS
#  remplir .env (clés API ci-dessus)
docker compose up -d                      # postgres + backend + frontend + worker + nginx
#  appliquer les migrations SQL (backend/database/migrations/*.sql) sur la base duret_sols
#  seed du catalogue de skills :
docker compose exec backend sh -c "PYTHONPATH=. python scripts/seed_skills_catalogue.py"
```
Frontend : http://localhost:3000 · connexion par lien magique (compte Resend requis).

## 6. Fait / à venir
- ✅ Copie indépendante, secrets neufs, thème bleu, rebrand complet (0 « Duret & Sols » résiduel).
- ✅ Prompts agents + catalogue de skills réorientés BTP ; extraction plans = revêtements/plinthes.
- ⏳ Connecteurs Duret (MyFiteco/Ediflex/Corus), logique métier des skills, dossier pilote, tests.

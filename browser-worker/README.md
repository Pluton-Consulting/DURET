# browser-worker — Agent de navigation agentique (browser-use)

Conteneur dédié, non exposé, qui exécute des tâches de navigation multi-étapes
pilotées par un LLM (recherche, login, formulaires, extraction). **Par défaut en
LECTURE SEULE** ; en mode écriture, l'approbation humaine des actions sensibles est
**best-effort** (voir §Sécurité).

## Architecture

```
Frontend (onglet Navigateur)
  └─ POST /api/browser/run ──► backend (routers/browser.py)
                                 ├─ crée browser_tasks (pending)
                                 └─ POST /run ──► browser-worker (asyncio.create_task)
                                                    └─ browser-use Agent (Chromium/Playwright)
                                                         ├─ navigue / lit / extrait (autonome)
                                                         └─ action modifiante → request_human_approval
                                                              ├─ INSERT validations (agent='browser')
                                                              └─ POLL statut ─┐
Frontend (ValidationQueue) ── POST /api/validations/{id}/resolve ─► UPDATE ───┘ (pas de resume_turn)
```

## Activation (checklist)

1. **Modèle LLM capable** (function-calling fiable — pas de llama-3.1-8b). Dans `.env` :
   ```
   BROWSER_AGENT_ENABLED=true
   BROWSER_LLM_PROVIDER=deepseek
   BROWSER_LLM_MODEL=deepseek-chat
   DEEPSEEK_API_KEY=sk-...
   BROWSER_ALLOWED_DOMAINS=extrabat.com,deytime.fr   # allowlist stricte
   INGESTION_WEBHOOK_SECRET=<déjà défini>            # pour l'extraction → RAG
   ```
2. **Identifiants par site** (facultatif, pour les logins) : copier
   `site_credentials.example.json` → `backend/secrets/site_credentials.json`
   (gitignoré). Les valeurs ne sont JAMAIS envoyées au LLM (`sensitive_data`).
3. **Migration** : appliquer `backend/database/migrations/012_browser_tasks.sql`.
4. **Build & run** :
   ```
   docker compose build browser-worker
   docker compose up -d browser-worker backend
   ```
5. Onglet **Navigateur** (super_admin / direction) → lancer une tâche.

## Sécurité

- `allowed_domains` (imposé par `sensitive_data`) + validation backend contre
  `BROWSER_ALLOWED_DOMAINS` : l'agent ne sort pas de l'allowlist.
- Secrets jamais dans les prompts, `validations.payload`, ni `audit_log`.
- Captures d'écran purgées du payload en `try/finally` (même en cas d'annulation/crash).
- `use_vision=false` par défaut (limite la fuite d'écran vers le LLM).
- **Mode lecture seule par défaut** (`BROWSER_READONLY=true`) : `input_text`/`send_keys`
  retirés du jeu d'actions → l'agent navigue/lit mais ne peut pas remplir/soumettre.
- ⚠ **En mode écriture** (`BROWSER_READONLY=false`), l'approbation avant action modifiante
  repose sur l'instruction au modèle (**best-effort**), PAS sur un verrou technique :
  browser-use ne permet pas d'imposer l'approbation avant un clic. Ne pas activer sur des
  comptes sensibles sans surveillance. **Le vrai verrou (« plan → approuver → exécuter »)
  reste à implémenter** — cf. faille de sécu #1.
- Identifiants scopés à l'hôte exact (`https://{domaine}`, pas `*.{domaine}`).

## Notes

- `browser-use==0.13.3` évolue vite : si le build ou un run révèle un écart d'API
  (nom de méthode de capture d'écran, kwargs de `Agent`/`Browser`), ajuster
  `browser_agent.py` en conséquence (le code est défensif mais pas garanti sur
  toutes les versions).
- Pour Extrabat, l'**API REST** (voir `backend/ingestion/connectors/extrabat.py`)
  reste préférable à l'automatisation UI quand elle est activable.

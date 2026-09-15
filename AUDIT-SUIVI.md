# Suivi de l'audit détaillé du 15/09 — Duret & Sols

Branche `audit/duret` (worktree `infra IA/DURET-audit`), partie du tag
`sauvegarde/avant-audit-2026-09-16` (8050e28). Document source : « Audit détaillé -
Duret et Symbiose.docx » (copie dans `infra IA/sauvegardes/2026-09-16-avant-audit/`).

Règles de Noa (16/09) : lot par lot (un lot + ses bancs → validation et déploiement
par Noa → lot suivant) ; opérations serveur = scripts + procédures que Noa lance ;
branches poussées sur benit seulement ; code admin « 0000 » à usage unique.

## Lot 1 — premier lot court + garde-fous

| Fiche | Sujet | État |
|---|---|---|
| D-02 | Styles Word conservés au remplacement, contrôle du fichier produit | fait (bancs réels) |
| D-05 | Échecs métier jamais présentés comme réussis | étape 1 faite (normaliseur, exécuteur, boucle, reprise) ; reçus avant « créé/envoyé » et preuves par requête : lot suivant |
| D-06 | Secours lexical quand les embeddings tombent | étape 1 faite (embedding et voie vectorielle isolés, diagnostic, panne ≠ absence) ; orchestrateur de sources et comparables NAS : lot 2 |
| D-03 | Bearer jamais envoyé à une origine externe ; propriété des visuels | à faire |
| D-27 | Doublons NAS : plus d'exclusion sur nom+taille | à faire |
| D-19 | Code admin : refus sur schéma incomplet, tentatives atomiques, « 0000 » à usage unique | à faire |
| D-22 | Export CSV neutralisé, export borné, secrets dans les traces | à faire |
| D-23 / D-26 / D-00 | Scripts de sauvegarde, de déploiement vérifié et procédure de recette | à faire |

## Journal

- 16/09 — D-02 : `bureautique/trame.py` réécrit le remplacement Word nœud `w:t` par nœud
  (styles des fragments, dessins, champs, zones de texte, tableaux imbriqués, en-têtes de
  première page) ; remplacements simultanés, chevauchements refusés ; formules Excel jamais
  réécrites ; `bureautique/controle.py` compare original et résultat rouvert. Bancs
  `test_trame_document` (+13), `test_reproduire_du_serveur`, `test_trame_pdf` verts avec
  python-docx/openpyxl/PyMuPDF réels.
- 16/09 — D-05 (étape 1) : `skills/resultats.py` (outcome, ok, effect_status, evidence_refs,
  warnings, retryable) ; `execute_skill` rend `ok` métier + champs d'avant, audit en échec ;
  `tools_node` et la reprise après accord suivent `ok`. Banc `test_resultats_normalises`.
- 16/09 — hors fiche (trouvé par la suite de bancs) : relances de facturation comptées au jour
  UTC — entre minuit et 2 h « relancée à l'instant » devenait « il y a 1 jour ». Jour à Paris.
- 16/09 — D-06 (étape 1) : `vectorstore/rag.py` calcule le vecteur hors du `try` de la recherche
  (`_embedding_sans_panne`), `retrieve_detaille` rend le diagnostic (API liste conservée),
  `search_hybrid` isole la voie vectorielle, `rechercher_documents` distingue panne (ok False,
  interdiction de conclure à l'absence) et « rien trouvé », et dit la couverture. Banc
  `test_recherche_documents` +5.

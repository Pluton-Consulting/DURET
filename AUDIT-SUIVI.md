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
| D-05 | Échecs métier jamais présentés comme réussis | à faire |
| D-06 | Secours lexical quand les embeddings tombent | à faire |
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

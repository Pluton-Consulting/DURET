> Mise à jour : lire d’abord `FIABILISATION-20260916.md`. Les compteurs et limites ci-dessous décrivent le passage précédent.

# Revue complémentaire du 16 septembre 2026 — DURET

Correctifs locaux non déployés. Rapport complet : `/Users/noa/Desktop/Vérification finale Duret et Symbiose - 16 septembre 2026/Rapport de vérification finale - Duret et Symbiose - 16 septembre 2026.docx`.

Les tests locaux ne clôturent pas toutes les fiches : nombreuses étapes 1, recette des connecteurs réels et opérations serveur encore nécessaires.

- Documents Word : remplacement et conservation de la structure : backend/bureautique/trame.py ; backend/bureautique/controle.py.
- Résultats après approbation : conserver les réserves : backend/skills/resultats.py ; backend/agents/router.py ; backend/agents/agent1.py.
- Recherche : une panne ne prouve pas une absence : backend/skills/documents.py ; backend/vectorstore/rag.py ; backend/vectorstore/client.py.
- Code généré : exécuter dans l’environnement annoncé : backend/sandbox/daytona_client.py.
- Actions externes : unicité atomique et refus sans registre : backend/skills/operations.py ; backend/agents/router.py.
- Embeddings : empêcher un ancien travailleur de réécrire : backend/vectorstore/client.py ; backend/vectorstore/worker.py ; backend/llm/budget.py.
- Reconnexion du chat : récupérer un résultat réel : backend/agents/requetes.py ; backend/routers/chat.py ; frontend/components/chat/ChatWindow.tsx.
- Connexion : borner aussi les demandes légitimes de lien : backend/routers/auth.py ; nginx/nginx.conf.
- Secrets : éviter une écriture en clair et mieux masquer : backend/security/coffre.py ; backend/security/secrets.py.
- Visuels : ne pas ouvrir un accès sur une anomalie de fichier : backend/visuels/depot.py.
- Restauration : une copie réellement séparée dans sa configuration : restaurer.sh.
- Sauvegardes simultanées et robustesse shell : backup.sh ; restaurer.sh.

Tests : 149 PASS / 0 FAIL / 3 SKIP ; 48 migrations sur base temporaire ; build Next.js et TypeScript réussis. Concurrence des opérations et baux exécutée sur PostgreSQL réel. Restauration simulée avec faux Docker seulement.

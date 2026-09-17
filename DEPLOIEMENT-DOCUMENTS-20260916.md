## Complément : documents longs, version renouvelée du 16 septembre

Recopier la nouvelle archive `DURET-2026-09-16.tar.gz`, le nouvel `SHA256SUMS` et l’installateur avant de suivre les étapes ci-dessus. Les anciennes archives du même nom ne contiennent pas ce complément.

Aucune nouvelle clé ni réinitialisation SQL. Les migrations déjà prévues jusqu’à 054 restent automatiques. `dossiers.sqlite3` et la file des rédactions sont créées dans le volume documentaire existant. La reconstruction du backend par l’installateur ajoute LibreOffice ; un simple redémarrage de l’ancien conteneur ne suffit pas.

Après la bascule, contrôler les nouveaux outils, le stockage et une vraie pagination :

```bash
CONTENEUR_IA="$(docker ps -q --filter label=com.docker.compose.project=duret-sols --filter label=com.docker.compose.service=backend)"
test -n "$CONTENEUR_IA"
docker exec "$CONTENEUR_IA" python /app/scripts/verifier_documents_durables.py
docker exec "$CONTENEUR_IA" python /app/scripts/test_documents_durables.py /app
```

Le premier contrôle ne contacte aucun fournisseur IA ni stockage métier. Le second utilise des fichiers temporaires et des modèles simulés ; l’export Langfuse privé n’est pas inclus dans l’archive, son test est donc signalé non joué sur le VPS. La pagination LibreOffice est testée réellement.

Rejouer ensuite la demande avec toutes ses pièces originales, notamment le Word de référence. Pour une rédaction importante, le chat peut annoncer le travail en arrière-plan ; son résultat revient dans la même conversation. Vérifier les rubriques, l’entreprise et le chantier actuels, les images, les 20 pages si demandées et les réserves. Pour les métrés, contrôler l’Excel, les niveaux, les postes, les unités et les citations.

Consulter le rapport `Documents longs - Rapport complémentaire.docx` pour le fonctionnement, les limites testées et les modules précis.

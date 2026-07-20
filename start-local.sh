#!/bin/bash
# Script de démarrage environnement local WSL2
# Lance l'équivalent du VPS en local

set -e

PROJECT_DIR="/mnt/c/Users/noa8b/Desktop/AI SYMBIOSE/symbiose-noa"
cd "$PROJECT_DIR"

echo "==> Démarrage du daemon Docker..."
if ! docker info > /dev/null 2>&1; then
  sudo service docker start
  sleep 3
fi

echo "==> Création du réseau Docker partagé..."
docker network create noa_network 2>/dev/null || echo "Réseau déjà existant"

echo "==> Lancement des services principaux..."
docker compose up -d --build

echo "==> Attente PostgreSQL..."
until docker compose exec postgres pg_isready -U noa_user -d symbiose_noa > /dev/null 2>&1; do
  sleep 2
done
echo "PostgreSQL prêt."

echo "==> Application des migrations..."
docker compose exec postgres psql -U noa_user -d symbiose_noa -f /migrations/001_initial_schema.sql 2>/dev/null || echo "Migration 001 déjà appliquée"
docker compose exec postgres psql -U noa_user -d symbiose_noa -f /migrations/002_magic_link_tokens.sql 2>/dev/null || echo "Migration 002 déjà appliquée"

echo ""
echo "=============================="
echo " NOA LOCAL — OPERATIONNEL"
echo "=============================="
echo " Frontend : http://localhost:3000"
echo " Backend  : http://localhost:8000"
echo " API docs : http://localhost:8000/api/docs"
echo "=============================="
echo ""
echo "Pour voir les logs : docker compose logs -f"
echo "Pour arrêter      : docker compose down"

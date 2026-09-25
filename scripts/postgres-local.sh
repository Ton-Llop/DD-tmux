#!/usr/bin/env bash
# Opción rápida: Postgres dentro de WSL (mientras no lo tengas en el homelab).
set -euo pipefail
sudo apt-get install -y postgresql
sudo service postgresql start
sudo -u postgres psql -v ON_ERROR_STOP=0 -c "CREATE USER dungeon PASSWORD 'dungeon'" -c "CREATE DATABASE dungeon OWNER dungeon" || true
echo "OK: postgresql://dungeon:dungeon@localhost:5432/dungeon"

#!/usr/bin/env bash
# Quick option: Postgres inside WSL (until you have it on the homelab).
set -euo pipefail
sudo apt-get install -y postgresql
sudo service postgresql start
sudo -u postgres psql -v ON_ERROR_STOP=0 -c "CREATE USER dungeon PASSWORD 'dungeon'" -c "CREATE DATABASE dungeon OWNER dungeon" || true
echo "OK: postgresql://dungeon:dungeon@localhost:5432/dungeon"

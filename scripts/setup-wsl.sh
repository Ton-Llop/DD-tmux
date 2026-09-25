#!/usr/bin/env bash
# Instala dependencias y genera .env. Ejecutar dentro de WSL desde la raíz del repo:
#   bash scripts/setup-wsl.sh
set -euo pipefail
cd "$(dirname "$0")/../backend"

command -v tmux >/dev/null || { echo "Instalando tmux..."; sudo apt-get update && sudo apt-get install -y tmux; }
command -v uv >/dev/null || { echo "Instalando uv..."; curl -LsSf https://astral.sh/uv/install.sh | sh; export PATH="$HOME/.local/bin:$PATH"; }
uv sync -q

if [ ! -f .env ]; then
  TOKEN=$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')
  read -rp "URL de Postgres [postgresql://dungeon:dungeon@localhost:5432/dungeon]: " DB
  DB=${DB:-postgresql://dungeon:dungeon@localhost:5432/dungeon}
  cat > .env <<ENV
TD_DATABASE_URL=$DB
TD_AUTH_TOKEN=$TOKEN
ENV
  chmod 600 .env
  echo; echo "Token generado (guárdalo, lo pide la web):"; echo "  $TOKEN"; echo
fi
echo "Listo. Arranca con: bash scripts/start.sh"

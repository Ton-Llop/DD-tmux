#!/usr/bin/env bash
# Installs dependencies and generates .env. Run inside WSL from the repo root:
#   bash scripts/setup-wsl.sh
set -euo pipefail
cd "$(dirname "$0")/../backend"

command -v tmux >/dev/null || { echo "Installing tmux..."; sudo apt-get update && sudo apt-get install -y tmux; }
command -v uv >/dev/null || { echo "Installing uv..."; curl -LsSf https://astral.sh/uv/install.sh | sh; export PATH="$HOME/.local/bin:$PATH"; }
uv sync -q

if [ ! -f .env ]; then
  TOKEN=$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')
  read -rp "Postgres URL [postgresql://dungeon:dungeon@localhost:5432/dungeon]: " DB
  DB=${DB:-postgresql://dungeon:dungeon@localhost:5432/dungeon}
  cat > .env <<ENV
TD_DATABASE_URL=$DB
TD_AUTH_TOKEN=$TOKEN
ENV
  chmod 600 .env
  echo; echo "Token generated (keep it, the web asks for it):"; echo "  $TOKEN"; echo
fi
echo "Done. Start with: bash scripts/start.sh"

#!/usr/bin/env bash
# Starts the backend + web on http://localhost:8765 (also reachable from Windows).
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"   # uv, also when launched from a tmux hook
cd "$(dirname "$0")/../backend"
set -a; source .env; set +a
exec uv run uvicorn app.main:app --host 127.0.0.1 --port "${TD_PORT:-8765}"

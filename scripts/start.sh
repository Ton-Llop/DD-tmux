#!/usr/bin/env bash
# Arranca el backend + web en http://localhost:8765 (accesible también desde Windows).
set -euo pipefail
cd "$(dirname "$0")/../backend"
set -a; source .env; set +a
exec uv run uvicorn app.main:app --host 127.0.0.1 --port "${TD_PORT:-8765}"

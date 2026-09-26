# tmux-dungeon — backend

FastAPI service that watches tmux, detects agents (Claude Code, Codex…), streams everything over
WebSocket and persists it in PostgreSQL. The pixel-art frontend only talks to this.

## Architecture

```
[machine with tmux]                         [Proxmox]
  tmux ── FastAPI backend :8765 ──────────▶ Postgres LXC
              ▲ (127.0.0.1)
   Cloudflare Tunnel / Tailscale  ◀── browser (phone, laptop…)
```

**Important:** the backend must run on the **same machine and user** as the tmux server
(it talks to the tmux CLI). If you run your agents in a homelab VM, put it there;
if you run them on your PC, it goes on your PC and only Postgres lives on Proxmox.

**Frontend:** served at `/` from `../frontend`.

**Security:** this service = a remote shell. A token is mandatory (min 24 chars, it won't start without one),
it listens only on 127.0.0.1 and is exposed through Cloudflare Tunnel + Access or Tailscale. Never open the port.

## Install

```bash
uv sync
cp .env.example .env   # fill in DB and token
uv run uvicorn app.main:app --port 8765      # or the bundled systemd unit
```
The schema is created on startup.

## How it works

- Every `poll_interval` (0.5 s): `tmux list-panes -a` + `capture-pane -e` for each pane.
- **Agent**: looks for `claude`/`codex` in the pane's process tree (`ps`).
- **State**: `working` (screen changed < 3 s ago), `idle`, `needs_input` (permission prompt
  like "Do you want to…", "(y/n)"), `dead`. → character animation.
- **Persistence** (`events`): session and pane open/close, state changes,
  everything you send (`input`/`key`) and plain-text screen snapshots
  (max 1 every 5 s per pane + always on entering `idle`/`needs_input` = the turn's result).
  Configurable retention (`TD_RETENTION_DAYS`).
- **Characters** (`characters`): `agent:<type>` = default per type, `slot:<session>:<win>.<pane>`
  = a specific pane (wins over the default). Character ids are free-form; the frontend
  maps them to sprites via `sprites/manifest.json`.

## WebSocket `/ws?token=…`
(or the `bearer.<token>` subprotocol so the token stays out of proxy logs)

Server → client:

| type | payload |
|---|---|
| `hello` | `panes[]`, `characters{}` |
| `session_open` / `session_close` | `session` |
| `pane_open` / `pane_update` | `pane` (includes `slot`, `agent`, `state`, `tail`, `character`) |
| `pane_close` | `pane_id`, `session` |
| `state` | `pane_id`, `session`, `agent`, `state`, `tail` (last 3 lines → speech bubble) |
| `screen` | `pane_id`, `content` (ANSI; subscribers only) |
| `characters` | `assignments{}`, `panes{pane_id: character}` |
| `history` | `id`, `events[]` |
| `ack` / `error` | `id`, `op` / `error` |

Client → server (all accept an `id` for correlation):

```json
{"op":"subscribe","pane_id":"%3"}            {"op":"unsubscribe","pane_id":"%3"}
{"op":"send_text","pane_id":"%3","text":"fix the test","enter":true}
{"op":"send_key","pane_id":"%3","key":"C-c"}   // Enter Escape Tab BSpace arrows C-c C-d …
{"op":"new_session","name":"api","cwd":"~/code/api","command":"claude"}
{"op":"kill_session","name":"api"}
{"op":"set_character","target":"agent:codex","character":"plague-doctor"}
{"op":"set_character","target":"slot:api:0.1","character":null}   // clear
{"op":"history","session":"api","kinds":["input","output"],"limit":50,"before_id":1234}
```

## REST (Bearer token)
`GET /api/panes` · `GET /api/panes/{id}/screen` · `GET /api/panes/{id}/diff` · `GET /api/history` ·
`POST /api/sessions` · `DELETE /api/sessions/{name}` · `POST /api/panes/{id}/text` ·
`POST /api/panes/{id}/key/{key}` · `GET|PUT /api/characters` · `GET /health`

# tmux-dungeon — backend

FastAPI que vigila tmux, detecta agentes (Claude Code, Codex…), emite todo por WebSocket
y persiste en PostgreSQL. El frontend pixel art (siguiente fase) solo habla con esto.

## Arquitectura

```
[máquina con tmux]                          [Proxmox]
  tmux ── backend FastAPI :8765 ──────────▶ LXC Postgres
              ▲ (127.0.0.1)
   Cloudflare Tunnel / Tailscale  ◀── navegador (móvil, portátil…)
```

**Importante:** el backend tiene que correr en la **misma máquina y usuario** que el servidor
tmux (habla con el CLI de tmux). Si lanzas los agentes en una VM del homelab, ponlo ahí;
si los lanzas en tu PC, va en tu PC y solo Postgres vive en Proxmox.

**Frontend:** se sirve en `/` desde `../frontend`.

**Seguridad:** este servicio = shell remota. Obligatorio token (min 24 chars, no arranca sin él),
escucha solo en 127.0.0.1 y se expone vía Cloudflare Tunnel + Access o Tailscale. Nunca abras el puerto.

## Instalación

```bash
uv sync
cp .env.example .env   # rellena DB y token
uv run uvicorn app.main:app --port 8765      # o el unit de systemd incluido
```
El esquema se crea solo al arrancar.

## Cómo funciona

- Cada `poll_interval` (0.5 s): `tmux list-panes -a` + `capture-pane -e` de cada pane.
- **Agente**: se busca `claude`/`codex` en el árbol de procesos del pane (`ps`).
- **Estado**: `working` (pantalla cambió < 3 s), `idle`, `needs_input` (prompt de permiso
  tipo "Do you want to…", "(y/n)"), `dead`. → animación del personaje.
- **Persistencia** (`events`): apertura/cierre de sesiones y panes, cambios de estado,
  todo lo que envías (`input`/`key`) y snapshots de pantalla en texto plano
  (máx 1 cada 5 s por pane + siempre al pasar a `idle`/`needs_input` = resultado del turno).
  Retención configurable (`TD_RETENTION_DAYS`).
- **Personajes** (`characters`): `agent:<tipo>` = default por tipo, `slot:<sesión>:<win>.<pane>`
  = pane concreto (gana sobre el default). Los ids de personaje son libres; el frontend los
  mapea a sprites vía `sprites/manifest.json`.

## WebSocket `/ws?token=…`
(o subprotocolo `bearer.<token>` para que el token no salga en logs de proxy)

Servidor → cliente:

| type | payload |
|---|---|
| `hello` | `panes[]`, `characters{}` |
| `session_open` / `session_close` | `session` |
| `pane_open` / `pane_update` | `pane` (incluye `slot`, `agent`, `state`, `tail`, `character`) |
| `pane_close` | `pane_id`, `session` |
| `state` | `pane_id`, `session`, `agent`, `state`, `tail` (últimas 3 líneas → bocadillo) |
| `screen` | `pane_id`, `content` (ANSI; solo a suscritos) |
| `characters` | `assignments{}`, `panes{pane_id: character}` |
| `history` | `id`, `events[]` |
| `ack` / `error` | `id`, `op` / `error` |

Cliente → servidor (todos aceptan `id` para correlacionar):

```json
{"op":"subscribe","pane_id":"%3"}            {"op":"unsubscribe","pane_id":"%3"}
{"op":"send_text","pane_id":"%3","text":"arregla el test","enter":true}
{"op":"send_key","pane_id":"%3","key":"C-c"}   // Enter Escape Tab BSpace flechas C-c C-d …
{"op":"new_session","name":"api","cwd":"~/code/api","command":"claude"}
{"op":"kill_session","name":"api"}
{"op":"set_character","target":"agent:codex","character":"plague-doctor"}
{"op":"set_character","target":"slot:api:0.1","character":null}   // quitar
{"op":"history","session":"api","kinds":["input","output"],"limit":50,"before_id":1234}
```

## REST (Bearer token)
`GET /api/panes` · `GET /api/panes/{id}/screen` · `GET /api/history` ·
`POST /api/sessions` · `DELETE /api/sessions/{name}` · `POST /api/panes/{id}/text` ·
`POST /api/panes/{id}/key/{key}` · `GET|PUT /api/characters` · `GET /health`

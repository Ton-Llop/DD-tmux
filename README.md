# DD-tmux

Tus sesiones de tmux como salas de una mazmorra pixel art. Cada agente (Claude Code, Codex…)
es un personaje: ataca cuando está trabajando, descansa junto a la hoguera cuando ha terminado
y levanta un **!** cuando te pide permiso. Al hacer clic en un personaje se abre su terminal en vivo,
desde donde le mandas órdenes, cambias de personaje o lees la crónica (histórico en Postgres).

```
DD-tmux/
├── backend/      FastAPI + WebSocket + PostgreSQL (vigila tmux)
├── frontend/     la web (la sirve el propio backend)
│   └── sprites/custom/   ← tus sprites (gitignored)
└── scripts/      setup y arranque en WSL
```

## Arranque rápido (WSL)

```bash
cd /mnt/c/Users/Ton/Documents/GitHub/DD-tmux
bash scripts/postgres-local.sh      # solo si aún no tienes Postgres en el homelab
bash scripts/setup-wsl.sh           # uv sync (backend/.venv) + .env con token
bash scripts/start.sh               # → http://localhost:8765 (también desde Windows)
ln -sf "$PWD/scripts/dd-tmux" ~/.local/bin/dd-tmux   # luego: dd-tmux [stop|log], en segundo plano
```

La web pide el token que imprimió `setup-wsl.sh` (está en `backend/.env`).

Lanza tus agentes como siempre (`tmux new -s api` → `claude`) y aparecerán solos.
También puedes crear salas desde la web con **+ Sala**.

### Postgres en el homelab

Levanta `backend/docker-compose.postgres.yml` en un LXC/VM de Proxmox y cambia
`TD_DATABASE_URL` en `backend/.env`. Limita el puerto 5432 a tu LAN con el firewall de Proxmox.

### Arranque automático en WSL (opcional)

Con systemd activado en WSL (`/etc/wsl.conf` → `[boot]\nsystemd=true`), copia
`backend/tmux-dungeon.service` a `~/.config/systemd/user/`, ajusta las rutas
(por defecto `~/DD-tmux`) y ejecuta `systemctl --user enable --now tmux-dungeon`.

### Acceso desde fuera de casa

El backend es una **shell remota**: escucha solo en `127.0.0.1` y nunca se abre el puerto.
Opciones, todas desde dentro de WSL:

- **Tailscale** (lo más sencillo): `tailscale serve 8765` → `https://<tu-pc>.<tailnet>.ts.net`
- **Cloudflare Tunnel + Access**: `cloudflared tunnel` hacia `http://localhost:8765`,
  con una política de Access (email) delante, además del token.

## Personajes

Los 6 que vienen de serie son originales: Templario, Hechicera, Ratero,
Ermitaño, Osario y Vagabundo. Por defecto: Claude → Templario, Codex → Hechicera, shell → Vagabundo.

Se cambian desde el panel (pestaña **Personaje**):
- **Solo este pane** → se guarda por `sesión:ventana.pane`, así que se mantiene aunque reinicies tmux
- **Todos los Claude/Codex** → default para ese tipo de agente

### Sprites propios

Pon tus imágenes en `frontend/sprites/custom/` y crea `manifest.json` (mira
`manifest.example.json`). Puedes usar una imagen por estado (`idle`, `working`, `needs_input`),
PNG o GIF animado (`"animated": true` desactiva las animaciones CSS). Tus personajes aparecen
en el selector junto a los de serie. Para cortar un sprite sheet de 8 poses en GIFs por estado:
`uv run --no-project --with pillow --with scipy scripts/cut_sprites.py` (mira `CHARS` dentro). La carpeta está en `.gitignore`: no subas a GitHub
assets con copyright de terceros.

## Cómo detecta las cosas

- **Agente**: busca `claude` / `codex` en el árbol de procesos de cada pane.
- **Estados**: `working` (la pantalla cambió hace < 3 s) · `idle` · `needs_input` (en el fondo
  de la pantalla aparece "Do you want to…", "(y/n)", "Allow…") · `dead`.
  Los patrones están en `backend/app/monitor.py` (`NEEDS_INPUT_RE`); añade los tuyos.
- **Crónica**: órdenes y teclas enviadas, cambios de estado y capturas de pantalla (máx. 1 cada 5 s
  por pane, más siempre la del final de cada turno). Retención: `TD_RETENTION_DAYS` (14).

Protocolo WebSocket y API REST: [`backend/README.md`](backend/README.md).

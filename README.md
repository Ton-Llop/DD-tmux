# DD-tmux

Tus sesiones de tmux como salas de una mazmorra al estilo Darkest Dungeon. Cada agente de IA
(Claude Code, Codex, Gemini…) es un personaje: trabaja cuando el agente está trabajando, duerme
cuando ha terminado y levanta un **!** cuando te pide permiso. Al hacer clic en un personaje se abre
su terminal en vivo, desde donde le mandas órdenes, cambias de personaje o lees la crónica
(histórico en Postgres).

```
DD-tmux/
├── backend/      FastAPI + WebSocket + PostgreSQL (vigila tmux)
├── frontend/     la web (la sirve el propio backend)
│   └── sprites/custom/   ← tus sprites y fondos (gitignored)
└── scripts/      setup, arranque y cortador de sprites
```

## Arranque rápido (WSL)

Necesitas [uv](https://docs.astral.sh/uv/) (el setup lo instala si falta) y tmux.

```bash
cd ~/projects/DD-tmux
bash scripts/postgres-local.sh      # solo si aún no tienes Postgres en el homelab
bash scripts/setup-wsl.sh           # uv sync (backend/.venv) + backend/.env con token
ln -sf "$PWD/scripts/dd-tmux" ~/.local/bin/dd-tmux
dd-tmux                             # arranca en segundo plano y abre http://localhost:8765
```

- `dd-tmux stop` lo para, `dd-tmux log` muestra el log. En primer plano: `bash scripts/start.sh`.
- Con el backend en marcha, los cambios del frontend y de los sprites solo piden recargar la web
  (Ctrl+F5). Los del backend (`backend/app/`) piden `dd-tmux stop && dd-tmux`.
- La web pide el token que imprimió `setup-wsl.sh` (`TD_AUTH_TOKEN` en `backend/.env`).

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

## La interfaz

- **Una sala a toda la ventana**: cada sesión de tmux es una sala y se ve una cada vez. El tamaño de
  los personajes lo fija `MAX_ZOOM` en `frontend/js/app.js` (1 = pequeños, con todo el fondo a la
  vista; 2, 3… = más grandes, siempre a zoom entero para que el pixel art no se deforme).
- **Mapa** (barra de abajo): las salas unidas por pasillos. Cada sala muestra **⚔** si alguien
  trabaja, **z** si todos descansan y un **!** rojo si alguien espera órdenes. Clic o **← →** para
  cambiar de sala. La web recuerda en qué sala estabas.
- **Actividad en el mapa**: sobre cada sala con alguien trabajando o esperando sale un bocadillo con
  lo que está haciendo. Clic en él y se despliega con todos los agentes de la sala y sus últimas
  líneas; clic en un agente te lleva a su terminal.
- **Fondos animados**: cada sala lleva uno de los fondos del manifest (salas seguidas, fondos
  distintos) con niebla y partículas según el ambiente. Sin fondos propios se usa el muro de serie.

## Personajes

No hay personajes de serie: salen todos del `manifest.json` (ver *Sprites propios*). Ahora mismo:
Bufón, Médico de la peste, Cazarrecompensas, Leproso y Vagabundo (el de las shells). El personaje por defecto de cada tipo de agente va en
`defaults` del manifest (`other-agent` = cualquier agente sin default propio); si falta, se usa el primero.

Se cambian desde el panel (pestaña **Personaje**):
- **Solo este panel** → se guarda por `sesión:ventana.pane`, así que se mantiene aunque reinicies tmux
- **Todos los Claude/Codex/…** → default para ese tipo de agente; además borra las asignaciones
  sueltas de los panes de ese tipo, para que el cambio llegue a todos

### Sprites propios

Todo va en `frontend/sprites/custom/` (en `.gitignore`: no subas a GitHub assets con copyright
de terceros) y se declara en `manifest.json` (mira `manifest.example.json`):

```jsonc
{
  "characters": {
    "bufon": {
      "name": "Bufón", "blurb": "ríe mientras degüella",
      "images": { "idle": "custom/bufon/sleep.gif", "working": "custom/bufon/lute.gif",
                  "needs_input": "custom/bufon/ask.gif", "dead": "custom/bufon/frame0.png" },
      "height": 130,          // alto en px "de juego"; la imagen puede ser mayor (se ve nítida con zoom)
      "animated": true        // GIF animado: desactiva las animaciones CSS de serie
    }
  },
  "defaults": { "claude": "bufon" },   // opcional: personaje por tipo de agente
  "backgrounds": [                     // opcional: fondos de sala, en este orden
    { "src": "custom/bg/mazmorra.jpg", "fx": "dungeon" }   // fx: dungeon | forest | storm | ashes
  ]
}
```

Efectos de fondo: `dungeon` (brasas y luz de antorcha), `forest` (luciérnagas), `storm` (lluvia y
relámpagos), `ashes` (ceniza cayendo y cielo que late). Van mejor imágenes panorámicas (~3:1) con
el suelo en el tercio de abajo.

### Cortar sprite sheets

`scripts/cut_sprites.py` convierte un sheet de 8 poses (2 filas de 4, fondo transparente) en los
GIFs de cada estado, alineados por los pies y a 390 px de alto (3× los 130 del manifest):

```bash
uv run --no-project --with pillow --with scipy scripts/cut_sprites.py [id ...]
```

Cada personaje es una carpeta `frontend/sprites/custom/<id>/` con `sheet.png` y una entrada en
`CHARS` dentro del script. Las poses se numeran 0-7 en orden de lectura:

```python
"cazador": {
    "work": ([0, 2, 4, 3, 2, 5], [650, 550, 400, 900, 500, 950]),  # poses y ms (uno para todas o uno por pose)
    "ask": ([6, 0], 600),
    "smooth": ["work", "ask"],               # fundidos entre poses + respiración (~13 fps)
    "sleep_in_sheet": (200, 0, 444, 127),    # durmiendo = pose de abajo a la derecha del sheet;
},                                           # la caja borra sus zetas fijas (px del recorte)
```

- **Sheets de una fila** (4 poses): `"rows": 1`. Si dos poses se tocan, el script las separa solo.
- **Durmiendo**: `sleep-src.png` en la carpeta (tumbado, fondo transparente), `sleep_in_sheet` o
  `"sleep_pose": N` (usa la pose N del sheet tal cual, p. ej. el Leproso dormita arrodillado).
  El cuerpo respira y aparecen 3 zetas una a una (las suyas si las trae sueltas; si no, las del Bufón).
- **Atrezo dibujado**: `PROPS` sustituye un GIF por una función propia (p. ej. `bard()`: notas
  musicales saliendo del laúd).

## Cómo detecta las cosas

- **Agente**: busca el ejecutable en el árbol de procesos de cada pane: Claude, Codex, Gemini,
  Aider, OpenCode, Cursor, Copilot, Qwen, Goose, Crush, Amp, Droid, Kiro y Cline. La lista
  (`AGENTS`) está en `backend/app/tmux.py`; añade el tuyo y su nombre en `AGENT_LABEL`
  (`frontend/js/app.js`).
- **Estados**: `working` (la pantalla cambió hace < 3 s) · `idle` · `needs_input` (en el fondo
  de la pantalla aparece "Do you want to…", "(y/n)", "Allow…") · `dead`.
  Los patrones están en `backend/app/monitor.py` (`NEEDS_INPUT_RE`); añade los tuyos.
- **Crónica**: órdenes y teclas enviadas, cambios de estado y capturas de pantalla (máx. 1 cada 5 s
  por pane, más siempre la del final de cada turno). Retención: `TD_RETENTION_DAYS` (14).

Protocolo WebSocket y API REST: [`backend/README.md`](backend/README.md).

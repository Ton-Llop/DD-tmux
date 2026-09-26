# DD-tmux

Your tmux sessions as rooms in a Darkest Dungeon-style dungeon. Every AI agent
(Claude Code, Codex, Gemini…) is a character: it works while the agent is working, sleeps
when it's done and raises a **!** when it asks for permission. Click a character to open
its live terminal, where you give it orders, change its character or read the chronicle
(history in Postgres).

```
DD-tmux/
├── backend/      FastAPI + WebSocket + PostgreSQL (watches tmux)
├── frontend/     the web UI (served by the backend itself)
│   └── sprites/custom/   ← characters and backgrounds (add your own here)
└── scripts/      setup, startup and sprite cutter
```

## Quick start (WSL)

You need [uv](https://docs.astral.sh/uv/) (the setup installs it if missing) and tmux.

```bash
cd ~/projects/DD-tmux
bash scripts/postgres-local.sh      # only if you don't have Postgres on the homelab yet
bash scripts/setup-wsl.sh           # uv sync (backend/.venv) + backend/.env with a token
ln -sf "$PWD/scripts/dd-tmux" ~/.local/bin/dd-tmux
dd-tmux                             # starts in the background and opens http://localhost:8765
```

- `dd-tmux stop` stops it, `dd-tmux log` shows the log. In the foreground: `bash scripts/start.sh`.
- With the backend running, frontend and sprite changes only need a page reload
  (Ctrl+F5). Backend changes (`backend/app/`) need `dd-tmux stop && dd-tmux`.
- The web asks for the token printed by `setup-wsl.sh` (`TD_AUTH_TOKEN` in `backend/.env`).

Launch your agents as usual (`tmux new -s api` → `claude`) and they show up on their own.
You can also create rooms from the web with **+ Room**.

### Postgres on the homelab

Bring up `backend/docker-compose.postgres.yml` in a Proxmox LXC/VM and change
`TD_DATABASE_URL` in `backend/.env`. Restrict port 5432 to your LAN with the Proxmox firewall.

### Autostart on WSL (optional)

With systemd enabled in WSL (`/etc/wsl.conf` → `[boot]\nsystemd=true`), copy
`backend/tmux-dungeon.service` to `~/.config/systemd/user/`, adjust the paths
(default `~/DD-tmux`) and run `systemctl --user enable --now tmux-dungeon`.

### Access from outside your home

The backend is a **remote shell**: it listens only on `127.0.0.1` and the port is never opened.
Options, all from inside WSL:

- **Tailscale** (the simplest): `tailscale serve 8765` → `https://<your-pc>.<tailnet>.ts.net`
- **Cloudflare Tunnel + Access**: `cloudflared tunnel` to `http://localhost:8765`,
  with an Access policy (email) in front, on top of the token.

## The interface

- **One room fills the window**: each tmux session is a room and you see one at a time. Character
  size is set by `MAX_ZOOM` in `frontend/js/app.js` (1 = small, with the whole background in
  view; 2, 3… = bigger, always at a whole zoom factor so the pixel art doesn't warp).
- **Map** (bottom bar): the rooms joined by corridors. Each room shows **⚔** if someone is
  working, **z** if everyone rests and a red **!** if someone awaits orders. Click or **← →** to
  change room. The web remembers which room you were in.
- **Activity on the map**: above every room with someone working or waiting there's a bubble with
  what they're doing. Click it to expand it with every agent in the room and their last
  lines; click an agent to jump to its terminal.
- **Animated backgrounds**: each room gets one of the manifest's backgrounds (neighbouring rooms get
  different ones) with fog and particles depending on the mood. Without custom backgrounds the stock wall is used.

## Characters

DD-tmux ships with 7 characters and 4 animated backgrounds, all declared in `manifest.json`:
Jester, Plague Doctor, Bounty Hunter, Leper, Joana, Volosin and Vagrant (the shell one).
Want more? See *Adding your own characters*. The default character for each agent type goes in
the manifest's `defaults` (`other-agent` = any agent without its own default); if missing, the first one is used.

Change them from the panel (**Character** tab):
- **This pane only** → stored by `session:window.pane`, so it survives a tmux restart
- **All Claude/Codex/…** → default for that agent type; it also clears the individual
  assignments of panes of that type, so the change reaches all of them

### Adding your own characters

1. Create a folder `frontend/sprites/custom/<id>/` with one image per state: GIFs or PNGs with a
   transparent background (`idle`, `working`, `needs_input`, optionally `dead`).
   Got a sprite sheet instead? Let `scripts/cut_sprites.py` make the GIFs (see *Cutting sprite sheets*).
2. Add an entry under `characters` in `frontend/sprites/custom/manifest.json`.
3. Reload the page (Ctrl+F5): it shows up in the **Character** tab.

Backgrounds work the same way: drop the image in `frontend/sprites/custom/bg/` and add it to `backgrounds`.
The manifest format (`manifest.example.json` is a minimal example):

```jsonc
{
  "characters": {
    "bufon": {
      "name": "Jester", "blurb": "laughs while he slits throats",
      "images": { "idle": "custom/bufon/sleep.gif", "working": "custom/bufon/lute.gif",
                  "needs_input": "custom/bufon/ask.gif", "dead": "custom/bufon/frame0.png" },
      "height": 130,          // height in "game" px; the image can be bigger (stays crisp when zoomed)
      "animated": true        // animated GIF: turns off the stock CSS animations
    }
  },
  "defaults": { "claude": "bufon" },   // optional: character per agent type
  "backgrounds": [                     // optional: room backgrounds, in this order
    { "src": "custom/bg/mazmorra.jpg", "fx": "dungeon" }   // fx: dungeon | forest | storm | ashes
  ]
}
```

Background effects: `dungeon` (embers and torchlight), `forest` (fireflies), `storm` (rain and
lightning), `ashes` (falling ash and a pulsing sky). Panoramic images (~3:1) with
the floor in the bottom third work best.

### Cutting sprite sheets

`scripts/cut_sprites.py` turns an 8-pose sheet (2 rows of 4, transparent background) into
one GIF per state, aligned by the feet and 390 px tall (3× the manifest's 130):

```bash
uv run --no-project --with pillow --with scipy scripts/cut_sprites.py [id ...]
```

Each character is a folder `frontend/sprites/custom/<id>/` with `sheet.png` and an entry in
`CHARS` inside the script. Poses are numbered 0-7 in reading order:

```python
"cazador": {
    "work": ([0, 2, 4, 3, 2, 5], [650, 550, 400, 900, 500, 950]),  # poses and ms (one for all or one per pose)
    "ask": ([6, 0], 600),
    "smooth": ["work", "ask"],               # crossfades between poses + breathing (~13 fps)
    "sleep_in_sheet": (200, 0, 444, 127),    # sleeping = the sheet's bottom-right pose;
},                                           # the box erases its baked-in z's (crop px)
```

- **Single-row sheets** (4 poses): `"rows": 1`. If two poses touch, the script splits them on its own.
- **Sleeping**: `sleep-src.png` in the folder (lying down, transparent background), `sleep_in_sheet` or
  `"sleep_pose": N` (uses sheet pose N as-is, e.g. the Leper dozes kneeling).
  The body breathes and 3 z's appear one by one (its own if they're loose; otherwise the Jester's).
- **Drawn props**: `PROPS` replaces a GIF with a custom function (e.g. `bard()`: musical
  notes coming out of the lute).

## How it detects things

- **Agent**: looks for the executable in each pane's process tree: Claude, Codex, Gemini,
  Aider, OpenCode, Cursor, Copilot, Qwen, Goose, Crush, Amp, Droid, Kiro and Cline. The list
  (`AGENTS`) is in `backend/app/tmux.py`; add yours and its name in `AGENT_LABEL`
  (`frontend/js/app.js`).
- **States**: `working` (the screen changed < 3 s ago) · `idle` · `needs_input` (the bottom
  of the screen shows "Do you want to…", "(y/n)", "Allow…") · `dead`.
  The patterns are in `backend/app/monitor.py` (`NEEDS_INPUT_RE`); add your own.
- **Chronicle**: orders and keys sent, state changes and screen captures (max. 1 every 5 s
  per pane, plus always the one at the end of each turn). Retention: `TD_RETENTION_DAYS` (14).

WebSocket protocol and REST API: [`backend/README.md`](backend/README.md).

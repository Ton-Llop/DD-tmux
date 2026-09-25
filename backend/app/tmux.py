"""Wrapper async sobre el CLI de tmux. Nunca pasa por una shell (sin inyección)."""
import asyncio
import re
from dataclasses import dataclass, asdict

from .config import settings

SEP = "|~|"  # tmux escapa los caracteres de control en -F, así que usamos uno imprimible
PANE_ID_RE = re.compile(r"^%\d+$")
SESSION_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")

# Tecla especial -> nombre tmux permitido
SPECIAL_KEYS = {"Enter", "Escape", "Tab", "BSpace", "Up", "Down", "Left", "Right",
                "C-c", "C-d", "C-l", "C-r", "C-z", "S-Tab", "PageUp", "PageDown"}

PANE_FORMAT = SEP.join([
    "#{session_name}", "#{session_id}", "#{window_index}", "#{window_name}",
    "#{pane_id}", "#{pane_index}", "#{pane_pid}", "#{pane_current_command}",
    "#{pane_current_path}", "#{pane_title}", "#{pane_active}", "#{pane_dead}",
    "#{pane_width}", "#{pane_height}",
])


class TmuxError(RuntimeError):
    pass


@dataclass
class Pane:
    session: str
    session_id: str
    window_index: int
    window_name: str
    pane_id: str
    pane_index: int
    pid: int
    command: str
    path: str
    title: str
    active: bool
    dead: bool
    width: int
    height: int
    agent: str = "shell"

    @property
    def slot(self) -> str:
        """Identificador estable del pane (los %ids de tmux cambian al reiniciar el servidor)."""
        return f"{self.session}:{self.window_index}.{self.pane_index}"

    def to_dict(self):
        return asdict(self) | {"slot": self.slot}


async def _run(*args: str, input_: bytes | None = None) -> str:
    base = ["tmux"] + (["-L", settings.tmux_socket] if settings.tmux_socket else [])
    proc = await asyncio.create_subprocess_exec(
        *base, *args,
        stdin=asyncio.subprocess.PIPE if input_ else None,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate(input_)
    if proc.returncode != 0:
        msg = err.decode(errors="replace").strip()
        # Sin servidor tmux corriendo = cero sesiones, no es un error
        if "no server running" in msg or "error connecting" in msg:
            return ""
        raise TmuxError(msg or f"tmux {args[0]} failed")
    return out.decode(errors="replace")


async def _process_tree() -> tuple[dict[int, list[int]], dict[int, str]]:
    """Una sola llamada a ps por tick: hijos por pid y cmdline por pid."""
    proc = await asyncio.create_subprocess_exec(
        "ps", "-eo", "pid=,ppid=,args=",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    out, _ = await proc.communicate()
    children: dict[int, list[int]] = {}
    args: dict[int, str] = {}
    for line in out.decode(errors="replace").splitlines():
        parts = line.split(None, 2)
        if len(parts) < 2:
            continue
        pid, ppid = int(parts[0]), int(parts[1])
        args[pid] = parts[2] if len(parts) > 2 else ""
        children.setdefault(ppid, []).append(pid)
    return children, args


def _descendant_cmdlines(pid: int, children, args, max_nodes: int = 200) -> str:
    """Cmdline del proceso del pane + todos sus descendientes (claude/codex corren bajo node/shell)."""
    out, stack, seen = [], [pid], 0
    while stack and seen < max_nodes:
        p = stack.pop()
        seen += 1
        out.append(args.get(p, ""))
        stack.extend(children.get(p, []))
    return " ".join(out)


def detect_agent(p: Pane, children, args) -> str:
    haystack = f"{p.command} {p.title} {_descendant_cmdlines(p.pid, children, args)}".lower()
    if "claude" in haystack:
        return "claude"
    if "codex" in haystack:
        return "codex"
    if any(k in haystack for k in ("aider", "gemini", "opencode")):
        return "other-agent"
    return "shell"


async def list_panes() -> list[Pane]:
    raw = await _run("list-panes", "-a", "-F", PANE_FORMAT)
    panes = []
    for line in raw.splitlines():
        f = line.split(SEP)
        if len(f) != 14:
            continue
        p = Pane(f[0], f[1], int(f[2]), f[3], f[4], int(f[5]), int(f[6]), f[7],
                 f[8], f[9], f[10] == "1", f[11] == "1", int(f[12]), int(f[13]))
        panes.append(p)
    if panes:
        children, args = await _process_tree()
        for p in panes:
            p.agent = detect_agent(p, children, args)
    return panes


async def capture(pane_id: str, lines: int | None = None, ansi: bool = True) -> str:
    _check_pane(pane_id)
    n = lines or settings.capture_lines
    args = ["capture-pane", "-p", "-J", "-t", pane_id, "-S", f"-{n}"]
    if ansi:
        args.insert(2, "-e")
    return await _run(*args)


async def send_text(pane_id: str, text: str, enter: bool = True):
    """Pega texto literal vía buffer (respeta multilínea y no interpreta nombres de tecla)."""
    _check_pane(pane_id)
    buf = f"td-{pane_id[1:]}"
    await _run("load-buffer", "-b", buf, "-", input_=text.encode())
    await _run("paste-buffer", "-d", "-p", "-b", buf, "-t", pane_id)
    if enter:
        await _run("send-keys", "-t", pane_id, "Enter")


async def send_key(pane_id: str, key: str):
    _check_pane(pane_id)
    if key not in SPECIAL_KEYS:
        raise TmuxError(f"tecla no permitida: {key}")
    await _run("send-keys", "-t", pane_id, key)


async def new_session(name: str, cwd: str | None = None, command: str | None = None):
    _check_session(name)
    args = ["new-session", "-d", "-s", name]
    if cwd:
        args += ["-c", cwd]
    await _run(*args)
    if command:  # se teclea en la shell nueva, así al salir del agente queda la shell
        panes = [p for p in await list_panes() if p.session == name]
        if panes:
            await send_text(panes[0].pane_id, command)


async def kill_session(name: str):
    _check_session(name)
    await _run("kill-session", "-t", f"={name}")


def _check_pane(pane_id: str):
    if not PANE_ID_RE.match(pane_id):
        raise TmuxError(f"pane id inválido: {pane_id}")


def _check_session(name: str):
    if not SESSION_RE.match(name):
        raise TmuxError(f"nombre de sesión inválido: {name}")

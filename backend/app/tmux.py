"""Async wrapper over the tmux CLI. Never goes through a shell (no injection)."""
import asyncio
import difflib
import json
import os
import re
import shlex
import sys
import tempfile
from dataclasses import dataclass, asdict
from pathlib import Path

from .config import settings

SEP = "|~|"  # tmux escapes control characters in -F, so we use a printable one
PANE_ID_RE = re.compile(r"^%\d+$")
SESSION_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")
CODE_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".css", ".sh", ".sql",
                   ".json", ".toml", ".yaml", ".yml", ".go", ".rs", ".java", ".kt",
                   ".swift", ".c", ".h", ".cpp", ".cs", ".rb", ".php", ".vue", ".svelte"}

# Special key -> allowed tmux name
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
        """Stable pane identifier (tmux %ids change when the server restarts)."""
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
        # No tmux server running = zero sessions, not an error
        if "no server running" in msg or "error connecting" in msg:
            return ""
        raise TmuxError(msg or f"tmux {args[0]} failed")
    return out.decode(errors="replace")


async def _process_tree() -> tuple[dict[int, list[int]], dict[int, str]]:
    """A single ps call per tick: children by pid and cmdline by pid."""
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
    """Cmdline of the pane process + all its descendants (claude/codex run under node/shell)."""
    out, stack, seen = [], [pid], 0
    while stack and seen < max_nodes:
        p = stack.pop()
        seen += 1
        out.append(args.get(p, ""))
        stack.extend(children.get(p, []))
    return " ".join(out)


# Known CLI agents: (type, regex over command + title + process-tree cmdlines).
# Order = priority. Short/ambiguous names (amp, droid) only count as an executable, not as a loose word.
EXE = r"(?:^|[\s/])"  # start of an executable: after a space or "/"
AGENTS = [
    ("claude", re.compile(r"claude")),
    ("codex", re.compile(r"\bcodex\b")),
    ("gemini", re.compile(r"\bgemini\b")),
    ("aider", re.compile(r"\baider\b")),
    ("opencode", re.compile(r"\bopencode\b")),
    ("cursor", re.compile(r"\bcursor-agent\b")),
    ("copilot", re.compile(r"\bcopilot\b")),
    ("qwen", re.compile(r"\bqwen\b")),
    ("goose", re.compile(EXE + r"goose(?:\s|$)")),
    ("crush", re.compile(EXE + r"crush(?:\s|$)")),
    ("amp", re.compile(EXE + r"amp(?:\s|$)")),
    ("droid", re.compile(EXE + r"droid(?:\s|$)")),
    ("kiro", re.compile(r"\bkiro-cli\b")),
    ("cline", re.compile(r"\bcline\b")),
]


def detect_agent(p: Pane, children, args) -> str:
    haystack = f"{p.command} {p.title} {_descendant_cmdlines(p.pid, children, args)}".lower()
    return next((kind for kind, rx in AGENTS if rx.search(haystack)), "shell")


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


async def code_diff(path: str) -> tuple[str, str, bool]:
    async def git(*args):
        proc = await asyncio.create_subprocess_exec(
            "git", "-C", path, *args,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=5)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise TmuxError("git diff took too long")
        if proc.returncode:
            raise TmuxError(err.decode(errors="replace").strip() or "not a Git repository")
        return out

    root = (await git("rev-parse", "--show-toplevel")).decode().strip()
    tracked = [p.decode(errors="surrogateescape") for p in
               (await git("diff", "--name-only", "-z", "HEAD")).split(b"\0") if p]
    tracked = [p for p in tracked if Path(p).suffix.lower() in CODE_EXTENSIONS]
    parts = [await git("diff", "--no-ext-diff", "--no-textconv", "--unified=3", "HEAD", "--", *tracked)] if tracked else []

    untracked = (await git("ls-files", "--others", "--exclude-standard", "-z")).split(b"\0")
    root_path = Path(root)
    for raw in untracked:
        if not raw:
            continue
        name = raw.decode(errors="surrogateescape")
        rel = Path(name)
        file = root_path / rel
        if rel.is_absolute() or ".." in rel.parts or rel.suffix.lower() not in CODE_EXTENSIONS:
            continue
        if file.is_symlink() or not file.is_file() or file.stat().st_size > 128_000:
            continue
        try:
            lines = file.read_text(encoding="utf-8").splitlines(keepends=True)
        except (OSError, UnicodeError):
            continue
        parts.append("".join(difflib.unified_diff([], lines, fromfile="/dev/null", tofile=f"b/{name}")).encode())

    diff = b"".join(parts)
    return root, diff[:500_000].decode(errors="replace"), len(diff) > 500_000


async def send_text(pane_id: str, text: str, enter: bool = True):
    """Pastes literal text via a buffer (keeps multiline and does not interpret key names)."""
    _check_pane(pane_id)
    buf = f"td-{pane_id[1:]}"
    await _run("load-buffer", "-b", buf, "-", input_=text.encode())
    await _run("paste-buffer", "-d", "-p", "-b", buf, "-t", pane_id)
    if enter:
        await _run("send-keys", "-t", pane_id, "Enter")


async def send_key(pane_id: str, key: str):
    _check_pane(pane_id)
    if key not in SPECIAL_KEYS:
        raise TmuxError(f"key not allowed: {key}")
    await _run("send-keys", "-t", pane_id, key)


async def new_session(name: str, cwd: str | None = None, command: str | None = None):
    _check_session(name)
    args = ["new-session", "-d", "-s", name]
    if cwd:
        args += ["-c", cwd]
    await _run(*args)
    if command:  # typed into the new shell, so the shell remains when the agent exits
        panes = [p for p in await list_panes() if p.session == name]
        if panes:
            command = _instrument_agent(command)
            await send_text(panes[0].pane_id, command)


def _instrument_agent(command: str) -> str:
    """Enable native tool hooks for the two built-in agents."""
    agent = command.strip().split(maxsplit=1)[0].rsplit("/", 1)[-1]
    hook = Path(__file__).with_name("agent_edit_hook.py")
    if agent == "claude":
        handlers = {
            event: [{"matcher": "Bash|Write|Edit|NotebookEdit|MultiEdit", "hooks": [{
                "type": "command", "command": shlex.join([sys.executable, str(hook), phase, "claude"])
            }]}]
            for event, phase in (("PreToolUse", "pre"), ("PostToolUse", "post"))
        }
        config_path = Path(tempfile.gettempdir()) / f"dd-tmux-claude-settings-{os.getuid()}.json"
        config_path.write_text(json.dumps({"bashEditDiffEnabled": True, "hooks": handlers}))
        config_path.chmod(0o600)
        return f"claude --settings {shlex.quote(str(config_path))}"
    if agent == "codex":
        args = []
        for event, phase in (("PreToolUse", "pre"), ("PostToolUse", "post")):
            handler_command = shlex.join([sys.executable, str(hook), phase, "codex"])
            value = [{"matcher": "Bash|apply_patch|Edit|Write", "hooks": [{
                "type": "command", "command": handler_command
            }]}]
            args += ["-c", shlex.quote(f"hooks.{event}={json.dumps(value)}")]
        return "codex " + " ".join(args)
    return command


async def kill_session(name: str):
    _check_session(name)
    await _run("kill-session", "-t", f"={name}")


def _check_pane(pane_id: str):
    if not PANE_ID_RE.match(pane_id):
        raise TmuxError(f"invalid pane id: {pane_id}")


def _check_session(name: str):
    if not SESSION_RE.match(name):
        raise TmuxError(f"invalid session name: {name}")

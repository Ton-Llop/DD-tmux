"""Capture one agent tool call's file changes and report its unified diff."""
import difflib
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".css", ".sh", ".sql",
             ".json", ".toml", ".yaml", ".yml", ".go", ".rs", ".java", ".kt",
             ".swift", ".c", ".h", ".cpp", ".cs", ".rb", ".php", ".vue", ".svelte"}
MAX_FILES = 4000
MAX_FILE_BYTES = 256_000
MAX_SNAPSHOT_BYTES = 8_000_000
MAX_DIFF_BYTES = 500_000


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5).stdout


def snapshot(root):
    names = git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z").split(b"\0")
    files, total = {}, 0
    for raw in names[:MAX_FILES]:
        if not raw:
            continue
        name = os.fsdecode(raw)
        path = Path(name)
        if path.is_absolute() or ".." in path.parts or path.suffix.lower() not in EXTENSIONS:
            continue
        target = root / path
        try:
            if target.is_symlink() or not target.is_file() or target.stat().st_size > MAX_FILE_BYTES:
                continue
            content = target.read_bytes()
        except OSError:
            continue
        total += len(content)
        if total > MAX_SNAPSHOT_BYTES:
            break
        try:
            files[name] = content.decode("utf-8")
        except UnicodeError:
            continue
    return files


def unified(before, after):
    out = []
    for name in sorted(before.keys() | after.keys()):
        old, new = before.get(name), after.get(name)
        if old == new:
            continue
        out.extend(difflib.unified_diff(
            old.splitlines(keepends=True) if old is not None else [],
            new.splitlines(keepends=True) if new is not None else [],
            fromfile=f"a/{name}" if old is not None else "/dev/null",
            tofile=f"b/{name}" if new is not None else "/dev/null"))
    return "".join(out)


def token():
    value = os.getenv("TD_AUTH_TOKEN")
    if value:
        return value
    env_file = Path(__file__).resolve().parents[1] / ".env"
    try:
        for line in env_file.read_text().splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() == "TD_AUTH_TOKEN":
                return value.strip().strip("\"'")
    except OSError:
        pass
    return ""


def main():
    phase, agent = sys.argv[1:3]
    event = json.load(sys.stdin)
    event.setdefault("cwd", event.get("workingDirectory"))
    event.setdefault("session_id", event.get("sessionId"))
    event.setdefault("tool_name", event.get("toolName"))
    if "tool_input" not in event and event.get("toolArgs"):
        try:
            event["tool_input"] = json.loads(event["toolArgs"])
        except (TypeError, ValueError):
            event["tool_input"] = event["toolArgs"]
    tool_name = str(event.get("tool_name") or "").lower()
    if tool_name and not any(word in tool_name for word in ("bash", "shell", "write", "edit", "patch", "file")):
        return
    pane = os.getenv("TMUX_PANE", "")
    if not re.fullmatch(r"%\d+", pane):
        return
    cwd = Path(event.get("cwd") or os.getcwd()).resolve()
    try:
        root = Path(os.fsdecode(git(cwd, "rev-parse", "--show-toplevel").strip())).resolve()
    except (subprocess.SubprocessError, OSError):
        return
    session_id = str(event.get("session_id") or "")
    tool_id = str(event.get("tool_use_id") or event.get("call_id") or "")
    if not tool_id:
        tool_input = json.dumps(event.get("tool_input", {}), sort_keys=True, separators=(",", ":"))
        tool_id = hashlib.sha256(f"{event.get('tool_name', '')}\0{tool_input}".encode()).hexdigest()
    key = hashlib.sha256(f"{pane}\0{session_id}\0{tool_id}".encode()).hexdigest()
    state = Path(tempfile.gettempdir()) / "dd-tmux-agent-edits" / f"{key}.json"

    if phase == "pre":
        try:
            state.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            data = {"root": str(root), "files": snapshot(root)}
            state.write_text(json.dumps(data))
        except (OSError, subprocess.SubprocessError):
            pass
        return

    try:
        before = json.loads(state.read_text())
        state.unlink()
    except (OSError, ValueError):
        return
    if before["root"] != str(root):
        return
    try:
        diff = unified(before["files"], snapshot(root))
    except (OSError, subprocess.SubprocessError):
        return
    if not diff:
        return
    diff = diff[:MAX_DIFF_BYTES]
    root_url = os.getenv("DD_TMUX_API_URL", "http://127.0.0.1")
    port = os.getenv("TD_PORT", "8765")
    if not os.getenv("DD_TMUX_API_URL"):
        try:
            for line in (Path(__file__).resolve().parents[1] / ".env").read_text().splitlines():
                key_name, sep, value = line.partition("=")
                if sep and key_name.strip() == "TD_PORT":
                    port = value.strip().strip("\"'")
        except OSError:
            pass
        root_url = f"http://127.0.0.1:{port}"
    payload = json.dumps({"agent": agent, "diff": diff,
                          "session_id": session_id, "tool_use_id": tool_id}).encode()
    request = urllib.request.Request(
        f"{root_url}/api/panes/{urllib.parse.quote(pane, safe='')}/agent-edits",
        data=payload, headers={"Authorization": f"Bearer {token()}",
                               "Content-Type": "application/json"})
    try:
        urllib.request.urlopen(request, timeout=2).close()
    except (OSError, urllib.error.URLError):
        pass


if __name__ == "__main__":
    main()

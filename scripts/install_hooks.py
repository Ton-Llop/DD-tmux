"""Enable DD-tmux edit tracking for every Claude Code session (not only rooms opened with + Room).

Adds PreToolUse/PostToolUse hooks that run backend/app/agent_edit_hook.py:
- Claude installed in Linux/WSL: ~/.claude/settings.json
- Claude for Windows launched from WSL (claude.exe): C:\\Users\\<you>\\.claude\\settings.json, calling the hook
  through wsl.exe, plus WSLENV=TMUX_PANE in ~/.bashrc so Windows Claude knows its tmux pane.
The hook does nothing outside tmux or when DD-tmux isn't running. Safe to run again: it won't duplicate.
"""
import json
import os
import shlex
import shutil
import subprocess
import time
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / "backend" / "app" / "agent_edit_hook.py"
MATCHER = "Bash|Write|Edit|NotebookEdit|MultiEdit"
BASHRC_LINE = 'export WSLENV="${WSLENV:+$WSLENV:}TMUX_PANE"   # dd-tmux: Windows Claude sees its tmux pane'


def install(settings_path: Path, command_for) -> bool:
    settings = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.is_file() else {}
    hooks = settings.setdefault("hooks", {})
    added = False
    for event, phase in (("PreToolUse", "pre"), ("PostToolUse", "post")):
        entry = {"matcher": MATCHER, "hooks": [{"type": "command", "command": command_for(phase), "timeout": 15}]}
        entries = hooks.setdefault(event, [])
        if entry in entries:
            continue
        # drop older dd-tmux entries (e.g. a previous path) and add the current one
        entries[:] = [e for e in entries if not any(HOOK.name in h.get("command", "") for h in e.get("hooks", []))]
        entries.append(entry)
        added = True
    if not added:
        print(f"Already enabled in {settings_path}")
        return False
    if settings_path.is_file():
        backup = settings_path.with_name(f"settings.json.bak-{time.strftime('%Y%m%d%H%M%S')}")
        shutil.copy2(settings_path, backup)
        print(f"Backup: {backup}")
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    print(f"Edit tracking enabled in {settings_path}")
    return True


def windows_home() -> Path | None:
    """C:\\Users\\<you> as a WSL path, or None when not running on WSL."""
    if not os.getenv("WSL_DISTRO_NAME") or not shutil.which("cmd.exe"):
        return None
    try:
        win = subprocess.run(["cmd.exe", "/c", "echo %USERPROFILE%"], cwd="/mnt/c", capture_output=True,
                             text=True, timeout=10).stdout.strip()
        return Path(subprocess.run(["wslpath", "-u", win], capture_output=True, text=True, timeout=5).stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return None


def main():
    # Claude installed in Linux / WSL
    install(Path.home() / ".claude" / "settings.json",
            lambda phase: shlex.join(["python3", str(HOOK), phase, "claude"]))

    # Claude for Windows, launched from WSL tmux panes
    home = windows_home()
    if home and (home / ".claude").is_dir():
        distro = os.environ["WSL_DISTRO_NAME"]
        # "//home/…": Windows Claude runs hooks in Git Bash, which rewrites "/home/…" into "C:/Program Files/Git/…"
        # when calling a Windows program; a leading "//" is left alone and is still a valid Linux path.
        install(home / ".claude" / "settings.json",
                lambda phase: shlex.join(["wsl.exe", "-d", distro, "-e", "python3", "/" + str(HOOK), phase, "claude"]))
        bashrc = Path.home() / ".bashrc"
        if "TMUX_PANE" not in (bashrc.read_text() if bashrc.is_file() else ""):
            with bashrc.open("a") as f:
                f.write(f"\n{BASHRC_LINE}\n")
            print(f"Added WSLENV=TMUX_PANE to {bashrc}")
        print("Windows Claude: open a new tmux pane (or run `source ~/.bashrc`) before starting it.")

    print("Restart any Claude already running so it picks up the hooks.")


if __name__ == "__main__":
    main()

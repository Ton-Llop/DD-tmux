# Code tab: see what your agent edited

The **Code** tab shows every change an agent makes to your files, as a red/green diff, one card per
edit. To do that, DD-tmux needs a tiny *hook* that runs before and after each agent action. This page
walks you through turning it on. It takes about two minutes and you only do it once.

> **Before you start:** DD-tmux must be installed and running (see the main [README](../README.md)),
> and your agent must work inside a **git repository** (a folder where `git status` works).

## 1. Which case are you?

Open a terminal **inside WSL/Linux** (the same place where you use tmux) and run:

```bash
command -v claude
```

| What it prints | You are in |
|---|---|
| Something like `/home/you/.local/bin/claude` | **Case A**: Claude Code installed in WSL/Linux |
| Something with `/mnt/c/...` in it (e.g. `/mnt/c/Users/You/AppData/Roaming/npm/claude`) | **Case B**: Claude Code for Windows, used from WSL |
| Nothing | Claude isn't installed in a place WSL can see. Install it first, then come back |
| You use **Codex, Gemini, OpenCode or Copilot** instead | **Case C** |

## Case A: Claude Code installed in WSL/Linux

1. Run this once:
   ```bash
   dd-tmux hooks
   ```
   You should see `Edit tracking enabled in /home/you/.claude/settings.json`.
2. **Close Claude completely** in every pane where it's open (type `/exit`, or press `Ctrl+D`),
   then start it again with `claude`.
3. Ask Claude to change something. Open its hero in DD-tmux → **Code** tab → **Refresh**. Done!

## Case B: Claude Code for Windows, used from WSL

This is a bit trickier, because a Windows program doesn't see tmux's variables by default.
`dd-tmux hooks` sets everything up for you:

1. Run this once, inside WSL:
   ```bash
   dd-tmux hooks
   ```
   You should see three things:
   - `Edit tracking enabled in /mnt/c/Users/You/.claude/settings.json` (your Windows Claude settings;
     a backup is saved next to it)
   - `Added WSLENV=TMUX_PANE to /home/you/.bashrc`
   - a reminder to open a new tmux pane
2. **Open a new tmux window or pane** (for example `tmux new-window`). A new one reads the updated
   `~/.bashrc`; the ones that were already open don't.
3. In that new pane, check that it worked:
   ```bash
   echo $WSLENV
   ```
   It must print `TMUX_PANE`. If it prints nothing, run `source ~/.bashrc` and check again.
4. Start Claude **from that pane** with `claude`.
   ⚠️ Restarting Claude from inside Claude doesn't count: it keeps its old settings. Quit it (`/exit`)
   and type `claude` in the shell.
5. Ask Claude to change something. Open its hero in DD-tmux → **Code** tab → **Refresh**. Done!

## Case C: Codex, Gemini, OpenCode or Copilot

Nothing to install. These agents report their edits when **DD-tmux launches them**:

1. In DD-tmux, click **+ Room** (bottom right).
2. Give the room a name, choose the project folder and pick the agent in **Launch**
   (for Gemini, OpenCode or Copilot choose *other command…* and type `gemini`, `opencode` or `copilot`).
3. Click **Open**. Edits made by that agent will show up in its **Code** tab.

Agents you start yourself with `tmux new` + `codex` (etc.) aren't tracked, only the ones opened with **+ Room**.

## It still doesn't show anything

Go through this list in order:

1. **Is DD-tmux running?** Open http://localhost:8765. If it doesn't load, run `dd-tmux`.
2. **Is it a git repository?** In the agent's folder, `git status` must work. Edits outside a git repo
   aren't tracked.
3. **Did the agent actually change a file?** Reading files or running commands that change nothing
   doesn't create an edit.
4. **Did you restart the agent after running `dd-tmux hooks`?** It has to be a fresh start from the
   shell (see step 4 of Case B).
5. **Case B only:** in the agent's pane, `echo $WSLENV` must print `TMUX_PANE`.
6. **Look at the hook log.** Every time the hook runs it writes one line here:
   ```bash
   tail -20 /tmp/dd-tmux-agent-edits/hook.log
   ```
   - No file at all → the hook never ran: go back to step 4 (restart the agent the right way).
   - `pre ... files in /your/project` then `post ... sent ... HTTP 200` → it works; press **Refresh**.
   - `no changes` → the agent didn't modify any file in that step.
   - `not a git repo` → see point 2.
   - `send failed` → DD-tmux isn't running (point 1).

## Turning it off

Open `~/.claude/settings.json` (Case A) or `C:\Users\You\.claude\settings.json` (Case B) and delete the
two entries under `hooks` whose command contains `agent_edit_hook.py`. For Case B you can also remove the
`WSLENV` line at the end of `~/.bashrc`.

## What the hook does (and doesn't do)

- Before and after each edit or command, it reads the text files of your git repository and sends the
  difference to DD-tmux on `127.0.0.1`. Nothing leaves your machine.
- Outside tmux, or when DD-tmux isn't running, it does nothing and never gets in the agent's way.
- In very big repositories it can add a short pause to each agent action (it reads up to 4000 files).

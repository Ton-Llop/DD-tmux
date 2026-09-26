"""Loop that scans tmux, detects changes and emits them over WS + Postgres."""
import asyncio
import hashlib
import logging
import re
import time
from dataclasses import dataclass, field

from . import db, tmux
from .config import settings
from .hub import hub

log = logging.getLogger("dungeon.monitor")

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07")
# Screens where the agent awaits your decision -> "needs_input" state
NEEDS_INPUT_RE = re.compile(
    r"do you want to|allow (this|once|always)|\(y/n\)|\[y/n\]|approve|"
    r"yes, and don't ask|press enter to|waiting for (your )?(approval|input)",
    re.IGNORECASE)


def strip_ansi(s: str) -> str:
    return ANSI_RE.sub("", s)


@dataclass
class PaneState:
    pane: tmux.Pane
    screen: str = ""
    digest: str = ""
    last_change: float = 0.0
    last_persist: float = 0.0
    persisted_digest: str = ""
    state: str = "idle"          # idle | working | needs_input | dead
    tail: list[str] = field(default_factory=list)
    last_sent: tuple = ()
    prompt: str = ""             # the question line when needs_input

    def public(self) -> dict:
        return self.pane.to_dict() | {"state": self.state, "tail": self.tail, "prompt": self.prompt,
                                      "last_change": self.last_change,
                                      "character": monitor.character_for(self.pane)}


CHAR_RE = re.compile(r"^[a-z0-9_\-]{1,40}$")
TARGET_RE = re.compile(r"^(slot:[A-Za-z0-9_.\-]{1,64}:\d+\.\d+|agent:[a-z\-]{1,20})$")


class Monitor:
    def __init__(self):
        self.panes: dict[str, PaneState] = {}
        self.sessions: set[str] = set()
        self.characters: dict[str, str] = {}   # target -> character id
        self._task: asyncio.Task | None = None

    def snapshot(self) -> list[dict]:
        return [ps.public() for ps in self.panes.values()]

    def character_for(self, pane: tmux.Pane) -> str | None:
        """Specific pane > agent-type default > None (the frontend uses its fallback)."""
        return (self.characters.get(f"slot:{pane.slot}")
                or self.characters.get(f"agent:{pane.agent}"))

    async def set_character(self, target: str, character: str | None):
        if not TARGET_RE.match(target):
            raise ValueError(f"invalid target: {target}")
        if character is not None and not CHAR_RE.match(character):
            raise ValueError(f"invalid character id: {character}")
        await db.set_character(target, character)
        if character:
            self.characters[target] = character
        else:
            self.characters.pop(target, None)
        if target.startswith("agent:") and character:
            # "All X" wins: clears the individual assignments of panes of that type
            agent = target.removeprefix("agent:")
            for ps in self.panes.values():
                slot = f"slot:{ps.pane.slot}"
                if ps.pane.agent == agent and slot in self.characters:
                    await db.set_character(slot, None)
                    del self.characters[slot]
        await hub.broadcast({"type": "characters", "assignments": self.characters,
                             "panes": {pid: self.character_for(ps.pane)
                                       for pid, ps in self.panes.items()}})

    def start(self):
        self._task = asyncio.create_task(self._start())

    async def _start(self):
        self.characters = await db.get_characters()
        await self._loop()

    async def stop(self):
        if self._task:
            self._task.cancel()

    async def _loop(self):
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("tick failed")
            await asyncio.sleep(settings.poll_interval)

    async def tick(self):
        now = time.time()
        panes = await tmux.list_panes()
        current = {p.pane_id: p for p in panes}

        # --- new / closed sessions
        sess = {p.session for p in panes}
        for s in sess - self.sessions:
            await db.touch_session(s)
            await db.log_event("session_open", session=s)
            await hub.broadcast({"type": "session_open", "session": s})
        for s in self.sessions - sess:
            await db.close_session(s)
            await db.log_event("session_close", session=s)
            await hub.broadcast({"type": "session_close", "session": s})
        self.sessions = sess

        # --- closed panes
        for pid in set(self.panes) - set(current):
            ps = self.panes.pop(pid)
            await self._persist(ps, force=True)
            await db.log_event("pane_close", ps.pane.session, pid, ps.pane.agent)
            await hub.broadcast({"type": "pane_close", "pane_id": pid, "session": ps.pane.session})

        # --- captures in parallel
        screens = await asyncio.gather(*(tmux.capture(pid) for pid in current),
                                       return_exceptions=True)
        for (pid, pane), screen in zip(current.items(), screens):
            if isinstance(screen, Exception):
                continue
            ps = self.panes.get(pid)
            if ps is None:
                ps = self.panes[pid] = PaneState(pane=pane, last_change=now)
                await db.log_event("pane_open", pane.session, pid, pane.agent,
                                   {"command": pane.command, "path": pane.path})
                await hub.broadcast({"type": "pane_open", "pane": ps.public()})
            else:
                changed = pane.agent != ps.pane.agent
                if changed:
                    await db.log_event("agent_change", pane.session, pid, pane.agent,
                                       {"from": ps.pane.agent})
                ps.pane = pane
                if changed:  # e.g. you launch `claude` in a shell: the character walks into the room
                    await hub.broadcast({"type": "pane_update", "pane": ps.public()})

            digest = hashlib.blake2b(screen.encode(), digest_size=12).hexdigest()
            if digest != ps.digest:
                ps.digest, ps.screen, ps.last_change = digest, screen, now
                plain = strip_ansi(screen).rstrip("\n").splitlines()
                ps.tail = [l for l in plain if l.strip()][-12:]  # the frontend picks the ones with text
                await hub.to_subscribers(pid, {"type": "screen", "pane_id": pid, "content": screen})

            await self._update_state(ps, now)
            if now - ps.last_persist >= settings.persist_interval:
                await self._persist(ps)

    async def _update_state(self, ps: PaneState, now: float):
        # capture-pane includes the pane's trailing empty rows: strip them before looking at the bottom
        lines = strip_ansi(ps.screen).rstrip().splitlines()
        bottom = lines[-15:]
        asking = [l.strip() for l in bottom if NEEDS_INPUT_RE.search(l)]
        ps.prompt = asking[-1][:120] if asking else ""
        if ps.pane.dead:
            new = "dead"
        elif ps.pane.agent != "shell" and asking:
            new = "needs_input"
        elif now - ps.last_change < settings.busy_window:
            new = "working"
        else:
            new = "idle"
        if new != ps.state:
            old, ps.state = ps.state, new
            await db.log_event("state", ps.pane.session, ps.pane.pane_id, ps.pane.agent,
                               {"from": old, "to": new})
            if new in ("idle", "needs_input"):  # stores the turn's final result
                await self._persist(ps, force=True)
        # state + tail to every client (feeds rooms and bubbles), only if something changed
        if (ps.state, ps.digest) != ps.last_sent:
            ps.last_sent = (ps.state, ps.digest)
            await hub.broadcast({"type": "state", "pane_id": ps.pane.pane_id,
                                 "session": ps.pane.session, "agent": ps.pane.agent,
                                 "state": ps.state, "tail": ps.tail, "prompt": ps.prompt})

    async def _persist(self, ps: PaneState, force: bool = False):
        if ps.digest == ps.persisted_digest or not ps.screen:
            return
        if not force and time.time() - ps.last_persist < settings.persist_interval:
            return
        ps.last_persist, ps.persisted_digest = time.time(), ps.digest
        await db.log_event("output", ps.pane.session, ps.pane.pane_id, ps.pane.agent,
                           {"screen": strip_ansi(ps.screen), "state": ps.state})


monitor = Monitor()

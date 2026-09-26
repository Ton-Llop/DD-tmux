import asyncio
import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db, tmux
from .config import settings
from .hub import Client, hub
from .monitor import monitor

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("dungeon")


async def _prune_loop():
    while True:
        try:
            await db.prune()
        except Exception:
            log.exception("prune")
        await asyncio.sleep(3600)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if len(settings.auth_token) < 24:
        raise RuntimeError("TD_AUTH_TOKEN missing or too short (min 24 chars). "
                           "Generate one: python -c 'import secrets;print(secrets.token_urlsafe(32))'")
    await db.connect()
    monitor.start()
    pruner = asyncio.create_task(_prune_loop())
    yield
    pruner.cancel()
    await monitor.stop()
    await db.close()


app = FastAPI(title="tmux-dungeon", lifespan=lifespan)


def _valid(token: str | None) -> bool:
    return bool(token) and secrets.compare_digest(token, settings.auth_token)


def require_auth(authorization: str | None = Header(None)):
    if not authorization or not _valid(authorization.removeprefix("Bearer ").strip()):
        raise HTTPException(401, "unauthorized")


# ---------------- REST ----------------
class NewSession(BaseModel):
    name: str = Field(pattern=tmux.SESSION_RE.pattern)
    cwd: str | None = None
    command: str | None = None   # e.g. "claude" or "codex"


class SendText(BaseModel):
    text: str = Field(max_length=100_000)
    enter: bool = True


class AgentEdit(BaseModel):
    agent: str = Field(pattern="^(claude|codex|gemini|opencode|copilot)$")
    diff: str = Field(min_length=1, max_length=500_000)
    session_id: str = Field(max_length=200)
    tool_use_id: str = Field(max_length=200)


@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/api/panes", dependencies=[Depends(require_auth)])
async def get_panes():
    return monitor.snapshot()


@app.get("/api/panes/{pane_id}/screen", dependencies=[Depends(require_auth)])
async def get_screen(pane_id: str, lines: int = 500, ansi: bool = True):
    try:
        return {"pane_id": pane_id, "content": await tmux.capture(pane_id, lines, ansi)}
    except tmux.TmuxError as e:
        raise HTTPException(400, str(e))


@app.get("/api/panes/{pane_id}/diff", dependencies=[Depends(require_auth)])
async def get_code_diff(pane_id: str):
    ps = monitor.panes.get(pane_id)
    if not ps:
        raise HTTPException(404, "pane not found")
    try:
        path, diff, truncated = await tmux.code_diff(ps.pane.path)
        return {"path": path, "diff": diff, "truncated": truncated}
    except tmux.TmuxError as e:
        raise HTTPException(400, str(e))


@app.get("/api/panes/{pane_id}/agent-edits", dependencies=[Depends(require_auth)])
async def get_agent_edits(pane_id: str, limit: int = 100):
    if pane_id not in monitor.panes:
        raise HTTPException(404, "pane not found")
    return await db.history(pane_id=pane_id, kinds=["code_edit"], limit=limit)


@app.post("/api/panes/{pane_id}/agent-edits", dependencies=[Depends(require_auth)])
async def post_agent_edit(pane_id: str, body: AgentEdit):
    ps = monitor.panes.get(pane_id)
    if not ps:
        raise HTTPException(404, "pane not found")
    if ps.pane.agent != body.agent:
        raise HTTPException(409, "agent does not match pane")
    await db.log_event("code_edit", ps.pane.session, pane_id, body.agent,
                       {"diff": body.diff, "session_id": body.session_id,
                        "tool_use_id": body.tool_use_id})
    return {"ok": True}


@app.get("/api/history", dependencies=[Depends(require_auth)])
async def get_history(session: str | None = None, pane_id: str | None = None,
                      kind: list[str] | None = Query(None), before_id: int | None = None,
                      limit: int = 100):
    return await db.history(session, pane_id, kind, before_id, limit)


@app.post("/api/sessions", dependencies=[Depends(require_auth)])
async def create_session(body: NewSession):
    await _do({"op": "new_session", **body.model_dump()})
    return {"ok": True}


@app.delete("/api/sessions/{name}", dependencies=[Depends(require_auth)])
async def delete_session(name: str):
    await _do({"op": "kill_session", "name": name})
    return {"ok": True}


@app.post("/api/panes/{pane_id}/text", dependencies=[Depends(require_auth)])
async def post_text(pane_id: str, body: SendText):
    await _do({"op": "send_text", "pane_id": pane_id, "text": body.text, "enter": body.enter})
    return {"ok": True}


class SetCharacter(BaseModel):
    target: str          # "slot:<session>:<win>.<pane>" or "agent:<type>"
    character: str | None = None  # None = clear assignment


@app.get("/api/characters", dependencies=[Depends(require_auth)])
async def get_characters():
    return monitor.characters


@app.put("/api/characters", dependencies=[Depends(require_auth)])
async def put_character(body: SetCharacter):
    await _do({"op": "set_character", **body.model_dump()})
    return monitor.characters


@app.post("/api/panes/{pane_id}/key/{key}", dependencies=[Depends(require_auth)])
async def post_key(pane_id: str, key: str):
    await _do({"op": "send_key", "pane_id": pane_id, "key": key})
    return {"ok": True}


# ---------------- actions shared by REST/WS ----------------
def _pane_meta(pane_id: str):
    ps = monitor.panes.get(pane_id)
    return (ps.pane.session, ps.pane.agent) if ps else (None, None)


async def _do(msg: dict):
    op = msg.get("op")
    try:
        if op == "send_text":
            await tmux.send_text(msg["pane_id"], str(msg["text"]), bool(msg.get("enter", True)))
            s, a = _pane_meta(msg["pane_id"])
            await db.log_event("input", s, msg["pane_id"], a, {"text": msg["text"]})
        elif op == "send_key":
            await tmux.send_key(msg["pane_id"], msg["key"])
            s, a = _pane_meta(msg["pane_id"])
            await db.log_event("key", s, msg["pane_id"], a, {"key": msg["key"]})
        elif op == "new_session":
            await tmux.new_session(msg["name"], msg.get("cwd"), msg.get("command"))
        elif op == "kill_session":
            await tmux.kill_session(msg["name"])
        elif op == "set_character":
            try:
                await monitor.set_character(msg["target"], msg.get("character"))
            except ValueError as e:
                raise HTTPException(400, str(e))
        else:
            raise HTTPException(400, f"unknown op: {op}")
    except tmux.TmuxError as e:
        raise HTTPException(400, str(e))
    except KeyError as e:
        raise HTTPException(400, f"missing field {e}")


# ---------------- WebSocket ----------------
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket, token: str | None = None):
    # Token via query (?token=) or as the "bearer.<token>" subprotocol (stays out of proxy logs)
    proto = next((p for p in ws.scope.get("subprotocols", []) if p.startswith("bearer.")), None)
    if not _valid(token or (proto.removeprefix("bearer.") if proto else None)):
        await ws.close(code=4401)
        return
    await ws.accept(subprotocol=proto)
    client = Client(ws)
    hub.add(client)
    await client.send({"type": "hello", "panes": monitor.snapshot(),
                       "characters": monitor.characters})
    try:
        while True:
            msg = await ws.receive_json()
            rid = msg.get("id")  # to correlate replies
            try:
                op = msg.get("op")
                if op == "subscribe":
                    pid = msg["pane_id"]
                    client.subs.add(pid)
                    ps = monitor.panes.get(pid)
                    if ps:  # current screen right away
                        await client.send({"type": "screen", "pane_id": pid, "content": ps.screen})
                elif op == "unsubscribe":
                    client.subs.discard(msg["pane_id"])
                elif op == "history":
                    rows = await db.history(msg.get("session"), msg.get("pane_id"),
                                            msg.get("kinds"), msg.get("before_id"),
                                            int(msg.get("limit", 100)))
                    await client.send({"type": "history", "id": rid, "events": rows})
                    continue
                else:
                    await _do(msg)
                await client.send({"type": "ack", "id": rid, "op": op})
            except HTTPException as e:
                await client.send({"type": "error", "id": rid, "error": e.detail})
            except Exception as e:  # noqa
                log.exception("ws op")
                await client.send({"type": "error", "id": rid, "error": str(e)})
    except WebSocketDisconnect:
        pass
    finally:
        hub.remove(client)


# ---------------- static frontend (goes last: doesn't shadow /api or /ws) ----------------
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

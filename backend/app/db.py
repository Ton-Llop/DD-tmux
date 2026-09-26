import json

import asyncpg

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    name        TEXT PRIMARY KEY,
    first_seen  TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen   TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at   TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS events (
    id       BIGSERIAL PRIMARY KEY,
    ts       TIMESTAMPTZ NOT NULL DEFAULT now(),
    session  TEXT,
    pane_id  TEXT,
    agent    TEXT,
    kind     TEXT NOT NULL,   -- session_open/close, pane_open/close, state, output, input, key
    data     JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS events_session_ts ON events (session, ts DESC);
CREATE INDEX IF NOT EXISTS events_pane_ts    ON events (pane_id, ts DESC);
CREATE INDEX IF NOT EXISTS events_kind_ts    ON events (kind, ts DESC);

-- Assigned character. target = 'slot:<session>:<window>.<pane>' (a specific pane)
--                             | 'agent:<type>'                   (default for claude, codex...)
CREATE TABLE IF NOT EXISTS characters (
    target     TEXT PRIMARY KEY,
    character  TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

pool: asyncpg.Pool | None = None


async def _init_conn(conn):
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


async def connect():
    global pool
    pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=5, init=_init_conn)
    async with pool.acquire() as c:
        await c.execute(SCHEMA)


async def close():
    if pool:
        await pool.close()


async def log_event(kind: str, session: str | None = None, pane_id: str | None = None,
                    agent: str | None = None, data: dict | None = None):
    await pool.execute(
        "INSERT INTO events (kind, session, pane_id, agent, data) VALUES ($1,$2,$3,$4,$5)",
        kind, session, pane_id, agent, data or {})


async def touch_session(name: str):
    await pool.execute(
        """INSERT INTO sessions (name) VALUES ($1)
           ON CONFLICT (name) DO UPDATE SET last_seen = now(), closed_at = NULL""", name)


async def close_session(name: str):
    await pool.execute("UPDATE sessions SET closed_at = now() WHERE name = $1", name)


async def history(session: str | None = None, pane_id: str | None = None,
                  kinds: list[str] | None = None, before_id: int | None = None, limit: int = 100):
    q = "SELECT id, ts, session, pane_id, agent, kind, data FROM events WHERE true"
    args = []
    for col, val in (("session", session), ("pane_id", pane_id)):
        if val:
            args.append(val)
            q += f" AND {col} = ${len(args)}"
    if kinds:
        args.append(kinds)
        q += f" AND kind = ANY(${len(args)})"
    if before_id:
        args.append(before_id)
        q += f" AND id < ${len(args)}"
    args.append(min(limit, 1000))
    q += f" ORDER BY id DESC LIMIT ${len(args)}"
    rows = await pool.fetch(q, *args)
    return [dict(r) | {"ts": r["ts"].isoformat()} for r in rows]


async def get_characters() -> dict[str, str]:
    return {r["target"]: r["character"] for r in await pool.fetch("SELECT target, character FROM characters")}


async def set_character(target: str, character: str | None):
    if character:
        await pool.execute(
            """INSERT INTO characters (target, character) VALUES ($1,$2)
               ON CONFLICT (target) DO UPDATE SET character = $2, updated_at = now()""",
            target, character)
    else:  # None = clear assignment (back to the default)
        await pool.execute("DELETE FROM characters WHERE target = $1", target)


async def prune():
    await pool.execute(
        "DELETE FROM events WHERE ts < now() - make_interval(days => $1)", settings.retention_days)

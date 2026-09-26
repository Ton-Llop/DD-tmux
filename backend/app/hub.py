"""WebSocket clients and their pane subscriptions."""
import asyncio
import json

from fastapi import WebSocket


class Client:
    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.subs: set[str] = set()       # panes whose full output it receives
        self.lock = asyncio.Lock()

    async def send(self, msg: dict):
        async with self.lock:
            await self.ws.send_text(json.dumps(msg, default=str))


class Hub:
    def __init__(self):
        self.clients: set[Client] = set()

    def add(self, c: Client):
        self.clients.add(c)

    def remove(self, c: Client):
        self.clients.discard(c)

    async def _send_many(self, targets, msg):
        dead = []
        for c, r in zip(targets, await asyncio.gather(*(c.send(msg) for c in targets),
                                                      return_exceptions=True)):
            if isinstance(r, Exception):
                dead.append(c)
        for c in dead:
            self.remove(c)

    async def broadcast(self, msg: dict):
        await self._send_many(list(self.clients), msg)

    async def to_subscribers(self, pane_id: str, msg: dict):
        await self._send_many([c for c in self.clients if pane_id in c.subs], msg)


hub = Hub()

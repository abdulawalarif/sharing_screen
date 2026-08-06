"""WebSocket signaling server for SDP / ICE exchange."""

from __future__ import annotations

import json
import logging
from typing import Any

from aiohttp import WSMsgType, web

logger = logging.getLogger(__name__)


class SignalingHub:
    """In-memory hub: one host + one viewer."""

    def __init__(self) -> None:
        self.host: web.WebSocketResponse | None = None
        self.viewer: web.WebSocketResponse | None = None

    def peer_of(self, ws: web.WebSocketResponse) -> web.WebSocketResponse | None:
        if ws is self.host:
            return self.viewer
        if ws is self.viewer:
            return self.host
        return None

    async def send(self, ws: web.WebSocketResponse | None, payload: dict[str, Any]) -> None:
        if ws is None or ws.closed:
            return
        await ws.send_str(json.dumps(payload))

    async def broadcast_ready(self) -> None:
        if self.host and self.viewer:
            await self.send(self.host, {"type": "ready", "role": "viewer"})
            await self.send(self.viewer, {"type": "ready", "role": "host"})


def create_app(hub: SignalingHub | None = None, ws_path: str = "/ws") -> web.Application:
    hub = hub or SignalingHub()
    app = web.Application()
    app["hub"] = hub

    async def health(_: web.Request) -> web.Response:
        h: SignalingHub = app["hub"]
        return web.json_response(
            {
                "ok": True,
                "host": h.host is not None and not h.host.closed,
                "viewer": h.viewer is not None and not h.viewer.closed,
            }
        )

    async def ws_handler(request: web.Request) -> web.WebSocketResponse:
        h: SignalingHub = request.app["hub"]
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        role: str | None = None
        logger.info("WebSocket connected from %s", request.remote)

        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    if msg.type in {WSMsgType.ERROR, WSMsgType.CLOSE}:
                        break
                    continue
                try:
                    data = json.loads(msg.data)
                except json.JSONDecodeError:
                    await h.send(ws, {"type": "error", "code": "invalid", "message": "Invalid JSON"})
                    continue

                msg_type = data.get("type")
                if msg_type == "hello":
                    role = data.get("role")
                    if role not in {"host", "viewer"}:
                        await h.send(
                            ws,
                            {
                                "type": "error",
                                "code": "invalid",
                                "message": "role must be host|viewer",
                            },
                        )
                        continue
                    if role == "host":
                        if h.host is not None and h.host is not ws and not h.host.closed:
                            await h.send(h.host, {"type": "bye", "reason": "peer_disconnected"})
                            await h.host.close()
                        h.host = ws
                        logger.info("Registered host")
                    else:
                        if h.viewer is not None and h.viewer is not ws and not h.viewer.closed:
                            await h.send(
                                ws,
                                {
                                    "type": "error",
                                    "code": "viewer_busy",
                                    "message": "Only one viewer is allowed",
                                },
                            )
                            continue
                        h.viewer = ws
                        logger.info("Registered viewer")
                    await h.broadcast_ready()
                    continue

                if role is None:
                    await h.send(
                        ws,
                        {"type": "error", "code": "invalid", "message": "Send hello first"},
                    )
                    continue

                if msg_type in {"offer", "answer", "ice", "stats"}:
                    peer = h.peer_of(ws)
                    if peer is None:
                        await h.send(
                            ws,
                            {
                                "type": "error",
                                "code": "peer_disconnected",
                                "message": "No peer connected",
                            },
                        )
                        continue
                    await h.send(peer, data)
                    continue

                await h.send(
                    ws,
                    {
                        "type": "error",
                        "code": "invalid",
                        "message": f"Unknown type: {msg_type}",
                    },
                )
        finally:
            logger.info("WebSocket closed role=%s", role)
            if h.host is ws:
                h.host = None
                await h.send(h.viewer, {"type": "bye", "reason": "peer_disconnected"})
            if h.viewer is ws:
                h.viewer = None
                await h.send(h.host, {"type": "bye", "reason": "peer_disconnected"})
            if not ws.closed:
                await ws.close()

        return ws

    app.router.add_get("/health", health)
    app.router.add_get(ws_path, ws_handler)
    return app


async def start_signaling(host: str, port: int, ws_path: str = "/ws") -> tuple[web.AppRunner, SignalingHub]:
    hub = SignalingHub()
    app = create_app(hub=hub, ws_path=ws_path)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=host, port=port)
    await site.start()
    logger.info("Signaling server listening on ws://%s:%s%s", host, port, ws_path)
    return runner, hub

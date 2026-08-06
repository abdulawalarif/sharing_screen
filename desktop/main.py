"""Desktop screen-share host: signaling + capture + WebRTC offerer."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import socket
from typing import Any

import aiohttp
from aiohttp import ClientWebSocketResponse

from config import AppConfig, default_config
from capture import create_capturer, detect_session
from signaling import start_signaling
from webrtc import WebRTCHost

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("desktop")


def lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


class HostSession:
    def __init__(self, cfg: AppConfig, force_capture: str | None) -> None:
        self.cfg = cfg
        self.force_capture = force_capture
        self.capturer = create_capturer(cfg.stream, force=force_capture)
        self.ws: ClientWebSocketResponse | None = None
        self.rtc: WebRTCHost | None = None
        self._offer_started = False
        self._session = aiohttp.ClientSession()

    async def start_capture(self) -> None:
        logger.info(
            "Starting capture backend=%s session=%s",
            self.capturer.backend_name,
            detect_session(),
        )
        await asyncio.to_thread(self.capturer.start)

    async def stop(self) -> None:
        if self.rtc is not None:
            await self.rtc.close()
            self.rtc = None
        if self.ws is not None and not self.ws.closed:
            await self.ws.close()
        await asyncio.to_thread(self.capturer.stop)
        await self._session.close()

    async def connect_signaling(self) -> None:
        url = f"ws://127.0.0.1:{self.cfg.server.port}{self.cfg.server.ws_path}"
        self.ws = await self._session.ws_connect(url, heartbeat=20)
        await self.ws.send_str(json.dumps({"type": "hello", "role": "host"}))
        logger.info("Host registered with signaling at %s", url)

    async def _send(self, payload: dict[str, Any]) -> None:
        if self.ws is None or self.ws.closed:
            return
        await self.ws.send_str(json.dumps(payload))

    async def _on_ice(self, payload: dict[str, Any]) -> None:
        await self._send(payload)

    async def _ensure_offer(self) -> None:
        if self._offer_started:
            return
        self._offer_started = True
        if self.rtc is not None:
            await self.rtc.close()
        self.rtc = WebRTCHost(
            capturer=self.capturer,
            stream=self.cfg.stream,
            on_ice=self._on_ice,
            prefer_codec=self.cfg.prefer_codec,
        )
        offer = await self.rtc.create_offer()
        await self._send(offer)
        logger.info("Sent WebRTC offer")

    async def handle_messages(self) -> None:
        assert self.ws is not None
        async for msg in self.ws:
            if msg.type != aiohttp.WSMsgType.TEXT:
                if msg.type in {aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR}:
                    break
                continue
            data = json.loads(msg.data)
            msg_type = data.get("type")
            if msg_type == "ready":
                logger.info("Peer ready (%s) — creating offer", data.get("role"))
                await self._ensure_offer()
            elif msg_type == "answer" and self.rtc is not None:
                await self.rtc.set_answer(data["sdp"])
                logger.info("Applied remote answer")
            elif msg_type == "ice" and self.rtc is not None:
                mid_index = data.get("sdpMLineIndex")
                if isinstance(mid_index, float):
                    mid_index = int(mid_index)
                await self.rtc.add_ice(
                    data.get("candidate"),
                    data.get("sdpMid"),
                    mid_index,
                )
            elif msg_type == "bye":
                logger.warning("Viewer disconnected — waiting for reconnect")
                self._offer_started = False
                if self.rtc is not None:
                    await self.rtc.close()
                    self.rtc = None
            elif msg_type == "error":
                logger.error("Signaling error: %s", data.get("message"))
            elif msg_type == "stats" and self.rtc is not None:
                # Echo timestamp for RTT estimate on the viewer.
                await self._send(
                    {
                        "type": "stats",
                        "t_client": data.get("t_client"),
                        "t_server": int(asyncio.get_running_loop().time() * 1000),
                        "frames_sent": self.rtc.frames_sent,
                        "connection": self.rtc.connection_state,
                    }
                )


async def run(cfg: AppConfig, force_capture: str | None) -> None:
    runner, _hub = await start_signaling(cfg.server.host, cfg.server.port, cfg.server.ws_path)
    ip = lan_ip()
    logger.info("LAN address for Wi-Fi viewers: ws://%s:%s%s", ip, cfg.server.port, cfg.server.ws_path)
    logger.info("ADB reverse (signaling only): adb reverse tcp:%s tcp:%s", cfg.server.port, cfg.server.port)

    session = HostSession(cfg, force_capture)
    stop = asyncio.Event()

    def _stop(*_: object) -> None:
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            pass

    try:
        await session.start_capture()
        await session.connect_signaling()
        reader = asyncio.create_task(session.handle_messages())
        waiter = asyncio.create_task(stop.wait())
        done, pending = await asyncio.wait({reader, waiter}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
    finally:
        await session.stop()
        await runner.cleanup()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Ubuntu → Android screen share (WebRTC host)")
    p.add_argument("--host", default="0.0.0.0", help="Signaling bind address")
    p.add_argument("--port", type=int, default=None, help="Signaling port")
    p.add_argument("--width", type=int, default=None)
    p.add_argument("--height", type=int, default=None)
    p.add_argument("--fps", type=int, default=None)
    p.add_argument("--bitrate", type=int, default=None, help="Max bitrate bits/sec")
    p.add_argument(
        "--capture",
        choices=["auto", "x11", "wayland"],
        default="auto",
        help="Force capture backend",
    )
    return p


def main() -> None:
    args = build_parser().parse_args()
    cfg = default_config()
    cfg.server.host = args.host
    if args.port is not None:
        cfg.server.port = args.port
    if args.width is not None:
        cfg.stream.width = args.width
    if args.height is not None:
        cfg.stream.height = args.height
    if args.fps is not None:
        cfg.stream.fps = args.fps
    if args.bitrate is not None:
        cfg.stream.max_bitrate_bps = args.bitrate
        cfg.stream.start_bitrate_bps = min(cfg.stream.start_bitrate_bps, args.bitrate)

    force = None if args.capture == "auto" else args.capture
    asyncio.run(run(cfg, force))


if __name__ == "__main__":
    main()

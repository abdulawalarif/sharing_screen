"""WebRTC transport: screen track + peer connection (desktop offerer)."""

from __future__ import annotations

import asyncio
import fractions
import logging
import time
from typing import Awaitable, Callable

import av
import numpy as np
from aiortc import (
    RTCConfiguration,
    RTCPeerConnection,
    RTCSessionDescription,
    VideoStreamTrack,
)
from aiortc.rtcrtpsender import RTCRtpSender

from ..capture.base import ScreenCapturer
from ..config import StreamConfig

logger = logging.getLogger(__name__)

IceCallback = Callable[[dict], Awaitable[None]]


class ScreenVideoTrack(VideoStreamTrack):
    """Pulls frames from a ScreenCapturer and paces them to the target FPS."""

    kind = "video"

    def __init__(self, capturer: ScreenCapturer, stream: StreamConfig) -> None:
        super().__init__()
        self._capturer = capturer
        self._stream = stream
        self._frame_interval = 1.0 / max(stream.fps, 1)
        self._next_frame_at = time.monotonic()
        self._start = time.monotonic()
        self.frames_sent = 0

    async def recv(self) -> av.VideoFrame:
        now = time.monotonic()
        delay = self._next_frame_at - now
        if delay > 0:
            await asyncio.sleep(delay)
        self._next_frame_at = max(self._next_frame_at + self._frame_interval, time.monotonic())

        grabbed = await asyncio.to_thread(self._capturer.grab)
        bgr: np.ndarray = grabbed.bgr
        if bgr.dtype != np.uint8:
            bgr = bgr.astype(np.uint8)
        frame = av.VideoFrame.from_ndarray(bgr, format="bgr24")
        frame.pts = int((time.monotonic() - self._start) * 90000)
        frame.time_base = fractions.Fraction(1, 90000)
        self.frames_sent += 1
        return frame


class WebRTCHost:
    """Desktop-side WebRTC peer: creates offer, sends H.264 screen track."""

    def __init__(
        self,
        capturer: ScreenCapturer,
        stream: StreamConfig,
        on_ice: IceCallback,
        prefer_codec: str = "H264",
    ) -> None:
        self._capturer = capturer
        self._stream = stream
        self._on_ice = on_ice
        self._prefer_codec = prefer_codec.upper()
        # No STUN/TURN — host candidates only (LAN / same subnet).
        self._pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        self._track: ScreenVideoTrack | None = None
        self._connected = asyncio.Event()
        self._codec_prefs = None

        @self._pc.on("icecandidate")
        async def on_icecandidate(candidate) -> None:  # type: ignore[no-untyped-def]
            if candidate is None:
                await self._on_ice(
                    {
                        "type": "ice",
                        "candidate": None,
                        "sdpMid": None,
                        "sdpMLineIndex": None,
                    }
                )
                return
            cand_sdp = candidate.to_sdp() if hasattr(candidate, "to_sdp") else str(candidate)
            await self._on_ice(
                {
                    "type": "ice",
                    "candidate": cand_sdp,
                    "sdpMid": candidate.sdpMid,
                    "sdpMLineIndex": candidate.sdpMLineIndex,
                }
            )

        @self._pc.on("connectionstatechange")
        async def on_state() -> None:
            logger.info("WebRTC connectionState=%s", self._pc.connectionState)
            if self._pc.connectionState == "connected":
                self._connected.set()
            if self._pc.connectionState in {"failed", "closed", "disconnected"}:
                self._connected.clear()

    @property
    def connection_state(self) -> str:
        return self._pc.connectionState

    @property
    def frames_sent(self) -> int:
        return self._track.frames_sent if self._track else 0

    async def create_offer(self) -> dict:
        self._prefer_h264()
        self._track = ScreenVideoTrack(self._capturer, self._stream)
        sender = self._pc.addTrack(self._track)
        await self._configure_sender(sender)

        offer = await self._pc.createOffer()
        await self._pc.setLocalDescription(offer)
        local = self._pc.localDescription
        assert local is not None
        return {"type": "offer", "sdp": local.sdp}

    async def set_answer(self, sdp: str) -> None:
        await self._pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type="answer"))

    async def add_ice(
        self,
        candidate: str | None,
        sdp_mid: str | None,
        sdp_mline_index: int | None,
    ) -> None:
        if not candidate:
            return
        from aiortc.sdp import candidate_from_sdp

        try:
            ice = candidate_from_sdp(candidate)
            ice.sdpMid = sdp_mid
            ice.sdpMLineIndex = sdp_mline_index
            await self._pc.addIceCandidate(ice)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to add ICE candidate")

    async def wait_connected(self, timeout: float = 30.0) -> None:
        await asyncio.wait_for(self._connected.wait(), timeout=timeout)

    async def close(self) -> None:
        await self._pc.close()
        self._track = None

    def _prefer_h264(self) -> None:
        caps = RTCRtpSender.getCapabilities("video")
        if not caps:
            return
        preferred = [c for c in caps.codecs if self._prefer_codec in c.mimeType.upper()]
        others = [c for c in caps.codecs if c not in preferred]
        if preferred:
            self._codec_prefs = preferred + others

    async def _configure_sender(self, sender: RTCRtpSender) -> None:
        for transceiver in self._pc.getTransceivers():
            if transceiver.sender == sender and hasattr(transceiver, "setCodecPreferences"):
                if self._codec_prefs:
                    try:
                        transceiver.setCodecPreferences(self._codec_prefs)
                    except Exception:  # noqa: BLE001
                        logger.debug("setCodecPreferences failed", exc_info=True)

        try:
            params = sender.getParameters()
            if params.encodings:
                params.encodings[0].maxBitrate = self._stream.max_bitrate_bps
                params.encodings[0].maxFramerate = float(self._stream.fps)
                await sender.setParameters(params)
        except Exception:  # noqa: BLE001
            logger.debug("Could not set sender bitrate parameters", exc_info=True)

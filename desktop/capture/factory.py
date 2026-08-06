"""Auto-detect session type and construct a capturer."""

from __future__ import annotations

import logging
import os

from config import StreamConfig
from capture.base import ScreenCapturer
from capture.x11 import X11Capturer

logger = logging.getLogger(__name__)


def detect_session() -> str:
    """Return ``wayland``, ``x11``, or ``unknown``."""
    session = (os.environ.get("XDG_SESSION_TYPE") or "").strip().lower()
    if session in {"wayland", "x11"}:
        return session
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"
    return "unknown"


def create_capturer(stream: StreamConfig, force: str | None = None) -> ScreenCapturer:
    kind = (force or detect_session()).lower()
    logger.info("Creating capturer for session=%s target=%sx%s@%sfps", kind, stream.width, stream.height, stream.fps)

    if kind == "wayland":
        from capture.wayland import WaylandCapturer, wayland_available

        if wayland_available():
            return WaylandCapturer(stream.width, stream.height, stream.fps)

        logger.warning(
            "Wayland detected but GStreamer/PipeWire GI bindings are missing; "
            "falling back to X11/mss (may be limited under Wayland). "
            "For proper Wayland capture install: python3-gi gir1.2-gstreamer-1.0 "
            "gstreamer1.0-plugins-base gstreamer1.0-pipewire xdg-desktop-portal"
        )
        if not os.environ.get("DISPLAY"):
            raise RuntimeError(
                "Wayland capture unavailable and no DISPLAY for X11 fallback. "
                "Install GStreamer portal packages or run an X11 session."
            )
        return X11Capturer(stream.width, stream.height, stream.fps)

    if kind in {"x11", "unknown"}:
        if kind == "unknown":
            logger.warning("Could not detect session type; falling back to X11/mss")
        return X11Capturer(stream.width, stream.height, stream.fps)

    raise ValueError(f"Unsupported capture backend: {kind}")

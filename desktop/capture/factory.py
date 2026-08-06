"""Auto-detect session type and construct a capturer."""

from __future__ import annotations

import logging
import os

from ..config import StreamConfig
from .base import ScreenCapturer
from .x11 import X11Capturer

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
        from .wayland import WaylandCapturer, wayland_available

        if not wayland_available():
            raise RuntimeError(
                "Wayland detected but GStreamer/PipeWire bindings are missing. "
                "Install: python3-gi gir1.2-gstreamer-1.0 gstreamer1.0-pipewire "
                "xdg-desktop-portal (and a backend such as xdg-desktop-portal-gnome/kde/wlr)."
            )
        return WaylandCapturer(stream.width, stream.height, stream.fps)

    if kind in {"x11", "unknown"}:
        if kind == "unknown":
            logger.warning("Could not detect session type; falling back to X11/mss")
        return X11Capturer(stream.width, stream.height, stream.fps)

    raise ValueError(f"Unsupported capture backend: {kind}")

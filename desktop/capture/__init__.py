"""Screen capture backends (X11 + Wayland)."""

from .base import ScreenCapturer, CaptureFrame
from .factory import create_capturer, detect_session

__all__ = [
    "ScreenCapturer",
    "CaptureFrame",
    "create_capturer",
    "detect_session",
]

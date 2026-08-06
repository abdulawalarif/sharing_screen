"""Screen capture backends (X11 + Wayland)."""

from capture.base import ScreenCapturer, CaptureFrame
from capture.factory import create_capturer, detect_session

__all__ = [
    "ScreenCapturer",
    "CaptureFrame",
    "create_capturer",
    "detect_session",
]

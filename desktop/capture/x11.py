"""X11 full-desktop capture via mss."""

from __future__ import annotations

import time

import cv2
import mss
import numpy as np

from capture.base import CaptureFrame, ScreenCapturer


class X11Capturer(ScreenCapturer):
    def __init__(self, width: int, height: int, fps: int, monitor: int = 1) -> None:
        super().__init__(width, height, fps)
        self._monitor_index = monitor
        self._sct: mss.mss | None = None
        self._monitor: dict | None = None

    @property
    def backend_name(self) -> str:
        return "x11-mss"

    def start(self) -> None:
        self._sct = mss.mss()
        monitors = self._sct.monitors
        idx = self._monitor_index
        if idx < 0 or idx >= len(monitors):
            idx = 1 if len(monitors) > 1 else 0
        self._monitor = monitors[idx]

    def stop(self) -> None:
        if self._sct is not None:
            self._sct.close()
            self._sct = None
        self._monitor = None

    def grab(self) -> CaptureFrame:
        if self._sct is None or self._monitor is None:
            raise RuntimeError("X11Capturer not started")

        shot = self._sct.grab(self._monitor)
        # mss returns BGRA
        bgra = np.asarray(shot, dtype=np.uint8)
        bgr = cv2.cvtColor(bgra, cv2.COLOR_BGRA2BGR)
        if bgr.shape[1] != self.width or bgr.shape[0] != self.height:
            bgr = cv2.resize(bgr, (self.width, self.height), interpolation=cv2.INTER_AREA)
        return CaptureFrame(bgr=bgr, timestamp=time.monotonic())

"""Capture abstractions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np


@dataclass(slots=True)
class CaptureFrame:
    """BGR24 frame buffer plus capture timestamp (monotonic seconds)."""

    bgr: np.ndarray
    timestamp: float


class ScreenCapturer(ABC):
    """Produces BGR frames from the desktop at a target size/FPS."""

    def __init__(self, width: int, height: int, fps: int) -> None:
        self.width = width
        self.height = height
        self.fps = fps

    @abstractmethod
    def start(self) -> None:
        ...

    @abstractmethod
    def stop(self) -> None:
        ...

    @abstractmethod
    def grab(self) -> CaptureFrame:
        ...

    @property
    @abstractmethod
    def backend_name(self) -> str:
        ...

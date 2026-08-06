"""Runtime configuration for the desktop screen-share host."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

_SHARED = Path(__file__).resolve().parents[1] / "shared" / "protocol.json"


def _load_defaults() -> dict:
    if _SHARED.exists():
        return json.loads(_SHARED.read_text(encoding="utf-8"))
    return {
        "default_port": 8080,
        "ws_path": "/ws",
        "defaults": {
            "width": 1280,
            "height": 720,
            "fps": 30,
            "max_bitrate_bps": 4_000_000,
            "min_bitrate_bps": 500_000,
            "start_bitrate_bps": 2_500_000,
        },
    }


_PROTO = _load_defaults()
_DEF = _PROTO["defaults"]


@dataclass(slots=True)
class StreamConfig:
    width: int = int(_DEF["width"])
    height: int = int(_DEF["height"])
    fps: int = int(_DEF["fps"])
    max_bitrate_bps: int = int(_DEF["max_bitrate_bps"])
    min_bitrate_bps: int = int(_DEF["min_bitrate_bps"])
    start_bitrate_bps: int = int(_DEF["start_bitrate_bps"])


@dataclass(slots=True)
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = int(_PROTO["default_port"])
    ws_path: str = str(_PROTO["ws_path"])


@dataclass(slots=True)
class AppConfig:
    stream: StreamConfig
    server: ServerConfig
    prefer_codec: str = "H264"


def default_config() -> AppConfig:
    return AppConfig(stream=StreamConfig(), server=ServerConfig())

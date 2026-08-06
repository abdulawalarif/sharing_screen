"""Ensure Debian/Ubuntu system GI modules (gi / GStreamer) are importable in a venv."""

from __future__ import annotations

import sys
from pathlib import Path


def enable_system_gi() -> None:
    """
    python3-gi is installed system-wide. Plain venvs hide /usr/lib/python3/dist-packages,
    so add it when needed.
    """
    try:
        import gi  # noqa: F401

        return
    except ImportError:
        pass

    candidates = [
        Path(f"/usr/lib/python{sys.version_info.major}.{sys.version_info.minor}/dist-packages"),
        Path("/usr/lib/python3/dist-packages"),
    ]
    for path in candidates:
        if path.is_dir() and str(path) not in sys.path:
            sys.path.append(str(path))
    # Retry is left to the caller.

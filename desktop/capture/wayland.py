"""Wayland full-desktop capture via xdg-desktop-portal + PipeWire/GStreamer."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any

import cv2
import numpy as np

from .base import CaptureFrame, ScreenCapturer

logger = logging.getLogger(__name__)


class WaylandCapturer(ScreenCapturer):
    """
    Uses the ScreenCast portal for a PipeWire node, then pulls frames with
    GStreamer ``pipewiresrc``.

    System packages typically required on Ubuntu:
    ``python3-gi``, ``gir1.2-gstreamer-1.0``, ``gstreamer1.0-plugins-base``,
    ``gstreamer1.0-pipewire``, ``xdg-desktop-portal``, and a portal backend.
    """

    def __init__(self, width: int, height: int, fps: int) -> None:
        super().__init__(width, height, fps)
        self._latest: CaptureFrame | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._error: BaseException | None = None
        self._thread: threading.Thread | None = None
        self._gst: Any = None
        self._pipeline: Any = None

    @property
    def backend_name(self) -> str:
        return "wayland-pipewire"

    def start(self) -> None:
        self._stop.clear()
        self._ready.clear()
        self._error = None
        self._thread = threading.Thread(target=self._run, name="wayland-capture", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=90):
            self.stop()
            raise TimeoutError(
                "Wayland ScreenCast portal timed out. Approve the screen-share prompt."
            )
        if self._error is not None:
            raise RuntimeError(f"Wayland capture failed: {self._error}") from self._error

    def stop(self) -> None:
        self._stop.set()
        if self._pipeline is not None and self._gst is not None:
            try:
                self._pipeline.set_state(self._gst.State.NULL)
            except Exception:  # noqa: BLE001
                logger.debug("Failed to stop GStreamer pipeline", exc_info=True)
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        self._pipeline = None

    def grab(self) -> CaptureFrame:
        with self._lock:
            frame = self._latest
        if frame is None:
            blank = np.zeros((self.height, self.width, 3), dtype=np.uint8)
            return CaptureFrame(bgr=blank, timestamp=time.monotonic())
        return frame

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            node_id = loop.run_until_complete(self._request_pipewire_node())
            self._start_gst(node_id)
            self._ready.set()
            while not self._stop.is_set():
                time.sleep(0.05)
        except BaseException as exc:  # noqa: BLE001
            self._error = exc
            logger.exception("Wayland capture thread failed")
            self._ready.set()
        finally:
            loop.close()

    async def _request_pipewire_node(self) -> int:
        from dbus_next import Variant
        from dbus_next.aio import MessageBus
        from dbus_next.constants import BusType

        bus = await MessageBus(bus_type=BusType.SESSION).connect()
        introspection = await bus.introspect(
            "org.freedesktop.portal.Desktop",
            "/org/freedesktop/portal/desktop",
        )
        desktop = bus.get_proxy_object(
            "org.freedesktop.portal.Desktop",
            "/org/freedesktop/portal/desktop",
            introspection,
        )
        screencast = desktop.get_interface("org.freedesktop.portal.ScreenCast")

        create_opts = {
            "handle_token": Variant("s", "sharing_screen_create"),
            "session_handle_token": Variant("s", "sharing_screen_session"),
        }
        session_result = await self._portal_request(bus, await screencast.call_create_session(create_opts))
        session_handle = session_result["session_handle"]
        if isinstance(session_handle, bytes):
            session_handle = session_handle.decode()

        select_opts = {
            "handle_token": Variant("s", "sharing_screen_select"),
            "types": Variant("u", 1),  # MONITOR
            "multiple": Variant("b", False),
            "cursor_mode": Variant("u", 2),  # Embedded
        }
        await self._portal_request(
            bus,
            await screencast.call_select_sources(session_handle, select_opts),
        )

        start_opts = {"handle_token": Variant("s", "sharing_screen_start")}
        start_result = await self._portal_request(
            bus,
            await screencast.call_start(session_handle, "", start_opts),
        )
        streams = start_result.get("streams")
        if not streams:
            raise RuntimeError("ScreenCast portal returned no streams")
        # streams: array of (node_id, props)
        first = streams[0]
        node_id = int(first[0] if isinstance(first, (list, tuple)) else first)
        logger.info("PipeWire ScreenCast node_id=%s", node_id)
        return node_id

    async def _portal_request(self, bus: Any, request_path: str) -> dict[str, Any]:
        from dbus_next import Variant

        introspection = await bus.introspect("org.freedesktop.portal.Desktop", request_path)
        request_obj = bus.get_proxy_object(
            "org.freedesktop.portal.Desktop",
            request_path,
            introspection,
        )
        request = request_obj.get_interface("org.freedesktop.portal.Request")
        future: asyncio.Future[tuple[int, dict[str, Any]]] = asyncio.get_running_loop().create_future()

        def on_response(response: int, results: Any) -> None:
            if future.done():
                return
            plain: dict[str, Any] = {}
            if isinstance(results, dict):
                for key, value in results.items():
                    plain[key] = value.value if isinstance(value, Variant) else value
            future.set_result((int(response), plain))

        request.on_response(on_response)
        response, results = await asyncio.wait_for(future, timeout=80)
        if response != 0:
            raise RuntimeError(f"Portal request failed/cancelled (response={response})")
        return results

    def _start_gst(self, node_id: int) -> None:
        import gi

        gi.require_version("Gst", "1.0")
        from gi.repository import Gst

        Gst.init(None)
        self._gst = Gst
        pipeline_str = (
            f"pipewiresrc path={node_id} do-timestamp=true ! "
            f"videoconvert ! video/x-raw,format=BGR ! "
            f"videoscale ! video/x-raw,width={self.width},height={self.height} ! "
            f"appsink name=sink emit-signals=true max-buffers=1 drop=true sync=false"
        )
        pipeline = Gst.parse_launch(pipeline_str)
        sink = pipeline.get_by_name("sink")
        sink.connect("new-sample", self._on_new_sample)
        ret = pipeline.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError("Failed to start pipewiresrc GStreamer pipeline")
        self._pipeline = pipeline

    def _on_new_sample(self, sink: Any) -> int:
        sample = sink.emit("pull-sample")
        if sample is None:
            return self._gst.FlowReturn.OK
        buf = sample.get_buffer()
        caps = sample.get_caps().get_structure(0)
        width = int(caps.get_value("width"))
        height = int(caps.get_value("height"))
        success, map_info = buf.map(self._gst.MapFlags.READ)
        if not success:
            return self._gst.FlowReturn.OK
        try:
            arr = np.frombuffer(map_info.data, dtype=np.uint8)
            expected = width * height * 3
            if arr.size < expected:
                return self._gst.FlowReturn.OK
            frame = arr[:expected].reshape((height, width, 3)).copy()
            if width != self.width or height != self.height:
                frame = cv2.resize(frame, (self.width, self.height), interpolation=cv2.INTER_AREA)
            with self._lock:
                self._latest = CaptureFrame(bgr=frame, timestamp=time.monotonic())
        finally:
            buf.unmap(map_info)
        return self._gst.FlowReturn.OK


def wayland_available() -> bool:
    try:
        import gi

        gi.require_version("Gst", "1.0")
        from gi.repository import Gst  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False

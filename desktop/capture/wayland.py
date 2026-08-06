"""Wayland full-desktop capture via xdg-desktop-portal + PipeWire/GStreamer."""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from typing import Any

import cv2
import numpy as np

from capture.base import CaptureFrame, ScreenCapturer
from capture.system_gi import enable_system_gi

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
        self._glib_loop: Any = None
        self._pw_fd: int | None = None
        # Keep portal D-Bus objects alive for the whole capture lifetime.
        # Dropping them destroys the ScreenCast session and pipewiresrc then
        # reports "target not found".
        self._bus: Any = None
        self._session_handle: str | None = None

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
        if self._glib_loop is not None:
            try:
                self._glib_loop.quit()
            except Exception:  # noqa: BLE001
                pass
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        self._pipeline = None
        if self._pw_fd is not None:
            try:
                os.close(self._pw_fd)
            except OSError:
                pass
            self._pw_fd = None
        self._bus = None
        self._session_handle = None

    def grab(self) -> CaptureFrame:
        with self._lock:
            frame = self._latest
        if frame is None:
            blank = np.zeros((self.height, self.width, 3), dtype=np.uint8)
            return CaptureFrame(bgr=blank, timestamp=time.monotonic())
        return frame

    def _run(self) -> None:
        try:
            enable_system_gi()
            import gi

            gi.require_version("GLib", "2.0")
            from gi.repository import GLib

            self._glib_loop = GLib.MainLoop()
            node_id, pw_fd = self._request_pipewire_stream()
            self._start_gst(node_id, pw_fd)
            self._ready.set()

            def _pump_stop() -> bool:
                if self._stop.is_set():
                    self._glib_loop.quit()
                    return False
                return True

            GLib.timeout_add(100, _pump_stop)
            self._glib_loop.run()
        except BaseException as exc:  # noqa: BLE001
            self._error = exc
            logger.exception("Wayland capture thread failed")
            self._ready.set()

    def _request_pipewire_stream(self) -> tuple[int, int]:
        enable_system_gi()
        import gi

        gi.require_version("Gio", "2.0")
        gi.require_version("GLib", "2.0")
        from gi.repository import Gio, GLib

        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self._bus = bus  # keep alive
        token = uuid.uuid4().hex[:8]
        session_token = f"ss{token}"
        create_token = f"create{token}"
        select_token = f"select{token}"
        start_token = f"start{token}"

        create_opts = {
            "handle_token": GLib.Variant("s", create_token),
            "session_handle_token": GLib.Variant("s", session_token),
        }
        create_result = self._portal_call(
            bus,
            "CreateSession",
            GLib.Variant("(a{sv})", (create_opts,)),
            create_token,
        )
        session_handle = create_result["session_handle"]
        if isinstance(session_handle, bytes):
            session_handle = session_handle.decode()
        self._session_handle = session_handle
        logger.info("ScreenCast session=%s", session_handle)

        select_opts = {
            "handle_token": GLib.Variant("s", select_token),
            "types": GLib.Variant("u", 1),
            "multiple": GLib.Variant("b", False),
            "cursor_mode": GLib.Variant("u", 2),
        }
        self._portal_call(
            bus,
            "SelectSources",
            GLib.Variant("(oa{sv})", (session_handle, select_opts)),
            select_token,
        )

        start_opts = {"handle_token": GLib.Variant("s", start_token)}
        start_result = self._portal_call(
            bus,
            "Start",
            GLib.Variant("(osa{sv})", (session_handle, "", start_opts)),
            start_token,
        )
        streams = start_result.get("streams")
        logger.info("ScreenCast streams=%r", streams)
        if not streams:
            raise RuntimeError("ScreenCast portal returned no streams")
        first = streams[0]
        node_id = int(first[0] if isinstance(first, (list, tuple)) else first)
        logger.info("PipeWire ScreenCast node_id=%s", node_id)

        result, fd_list = bus.call_with_unix_fd_list_sync(
            "org.freedesktop.portal.Desktop",
            "/org/freedesktop/portal/desktop",
            "org.freedesktop.portal.ScreenCast",
            "OpenPipeWireRemote",
            GLib.Variant("(oa{sv})", (session_handle, {})),
            GLib.VariantType("(h)"),
            Gio.DBusCallFlags.NONE,
            30_000,
            None,
            None,
        )
        handle_index = int(result.unpack()[0])
        # Steal FDs so ownership transfers to us (not closed with fd_list).
        stolen = list(fd_list.steal_fds())
        pw_fd = int(stolen[handle_index])
        logger.info("PipeWire remote fd=%s (stolen index=%s)", pw_fd, handle_index)
        self._pw_fd = pw_fd

        # Give the portal remote a moment to publish the stream node.
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            GLib.main_context_default().iteration(False)
            time.sleep(0.01)

        return node_id, pw_fd

    def _portal_call(
        self,
        bus: Any,
        method: str,
        parameters: Any,
        handle_token: str,
    ) -> dict[str, Any]:
        """Call a ScreenCast method and wait for the Request Response signal."""
        from gi.repository import Gio, GLib

        sender_name = bus.get_unique_name()
        sender_path = sender_name[1:].replace(".", "_")
        request_path = f"/org/freedesktop/portal/desktop/request/{sender_path}/{handle_token}"

        done = threading.Event()
        result_box: dict[str, Any] = {"response": None, "results": None, "error": None}

        def on_signal(
            _connection: Any,
            _sender: str,
            _object_path: str,
            _interface_name: str,
            _signal_name: str,
            args: Any,
            *_user_data: Any,
        ) -> None:
            try:
                payload = args.unpack() if hasattr(args, "unpack") else tuple(args)
                response = int(payload[0])
                results_v = payload[1]
                plain: dict[str, Any] = {}
                if hasattr(results_v, "unpack"):
                    results_v = results_v.unpack()
                if isinstance(results_v, dict):
                    for key, value in results_v.items():
                        plain[key] = value.unpack() if hasattr(value, "unpack") else value
                result_box["response"] = response
                result_box["results"] = plain
            except Exception as exc:  # noqa: BLE001
                result_box["error"] = exc
            finally:
                done.set()

        sub_id = bus.signal_subscribe(
            "org.freedesktop.portal.Desktop",
            "org.freedesktop.portal.Request",
            "Response",
            request_path,
            None,
            Gio.DBusSignalFlags.NONE,
            on_signal,
            None,
        )
        try:
            bus.call_sync(
                "org.freedesktop.portal.Desktop",
                "/org/freedesktop/portal/desktop",
                "org.freedesktop.portal.ScreenCast",
                method,
                parameters,
                GLib.VariantType("(o)"),
                Gio.DBusCallFlags.NONE,
                30_000,
                None,
            )

            deadline = time.monotonic() + 80
            while not done.is_set():
                if time.monotonic() > deadline:
                    raise TimeoutError(f"Portal {method} timed out waiting for Response")
                GLib.main_context_default().iteration(True)

            if result_box["error"] is not None:
                raise result_box["error"]
            if result_box["response"] != 0:
                raise RuntimeError(
                    f"Portal {method} denied/cancelled (response={result_box['response']}). "
                    "Click Share/Allow on the desktop prompt."
                )
            return result_box["results"] or {}
        finally:
            bus.signal_unsubscribe(sub_id)

    def _start_gst(self, node_id: int, pw_fd: int) -> None:
        enable_system_gi()
        import gi

        gi.require_version("Gst", "1.0")
        from gi.repository import Gst

        Gst.init(None)
        self._gst = Gst

        # Build the pipeline in code so we can set fd / target-object reliably.
        # `path` is deprecated on PipeWire 1.x; prefer `target-object`.
        attempts: list[dict[str, Any]] = [
            {"fd": pw_fd, "target-object": str(node_id)},
            {"fd": pw_fd, "path": str(node_id)},
            {"fd": pw_fd},  # autoconnect on the portal-restricted remote
        ]

        last_error: Exception | None = None
        for props in attempts:
            pipeline = None
            try:
                pipeline = Gst.Pipeline.new("screen-capture")
                src = Gst.ElementFactory.make("pipewiresrc", "src")
                convert = Gst.ElementFactory.make("videoconvert", "convert")
                scale = Gst.ElementFactory.make("videoscale", "scale")
                caps = Gst.ElementFactory.make("capsfilter", "caps")
                sink = Gst.ElementFactory.make("appsink", "sink")
                if not all([src, convert, scale, caps, sink]):
                    raise RuntimeError("Missing GStreamer elements (pipewiresrc/videoconvert/...)")

                for key, value in props.items():
                    src.set_property(key, value)
                src.set_property("do-timestamp", True)

                caps.set_property(
                    "caps",
                    Gst.Caps.from_string(
                        f"video/x-raw,format=BGR,width={self.width},height={self.height}"
                    ),
                )
                sink.set_property("emit-signals", True)
                sink.set_property("max-buffers", 1)
                sink.set_property("drop", True)
                sink.set_property("sync", False)
                sink.connect("new-sample", self._on_new_sample)

                for element in (src, convert, scale, caps, sink):
                    pipeline.add(element)
                if not src.link(convert):
                    raise RuntimeError("link pipewiresrc→videoconvert failed")
                if not convert.link(scale):
                    raise RuntimeError("link videoconvert→videoscale failed")
                if not scale.link(caps):
                    raise RuntimeError("link videoscale→caps failed")
                if not caps.link(sink):
                    raise RuntimeError("link caps→appsink failed")

                bus = pipeline.get_bus()
                logger.info("Starting pipewiresrc with %s", props)
                ret = pipeline.set_state(Gst.State.PLAYING)
                if ret == Gst.StateChangeReturn.FAILURE:
                    raise RuntimeError("state change FAILURE")

                # Wait for PLAYING or an error (registry lookup happens async).
                state_ret, state, _pending = pipeline.get_state(3 * Gst.SECOND)
                if bus is not None:
                    while True:
                        msg = bus.pop_filtered(Gst.MessageType.ERROR | Gst.MessageType.EOS)
                        if msg is None:
                            break
                        if msg.type == Gst.MessageType.ERROR:
                            err, debug = msg.parse_error()
                            raise RuntimeError(f"{err.message} ({debug})")

                if state_ret != Gst.StateChangeReturn.SUCCESS or state != Gst.State.PLAYING:
                    # One more error check
                    if bus is not None:
                        msg = bus.timed_pop_filtered(Gst.SECOND, Gst.MessageType.ERROR)
                        if msg is not None:
                            err, debug = msg.parse_error()
                            raise RuntimeError(f"{err.message} ({debug})")
                    raise RuntimeError(f"pipeline not PLAYING (ret={state_ret}, state={state})")

                logger.info("GStreamer pipeline PLAYING with %s", props)
                self._pipeline = pipeline
                return
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning("GStreamer attempt %s failed: %s", props, exc)
                if pipeline is not None:
                    try:
                        pipeline.set_state(Gst.State.NULL)
                    except Exception:  # noqa: BLE001
                        pass

        raise RuntimeError(f"pipewiresrc failed: {last_error}")

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
        enable_system_gi()
        import gi

        gi.require_version("Gst", "1.0")
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio, Gst  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False

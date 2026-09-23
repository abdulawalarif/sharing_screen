# sharing_screen

Ubuntu desktop → Android screen mirroring over **WebRTC (H.264)** with a small **WebSocket signaling** server.

```
sharing_screen/
  desktop/       # Python host: capture + WebRTC offerer + signaling
  flutter_app/   # Flutter Android viewer (flutter_webrtc)
  shared/        # Signaling protocol docs + defaults
  README.md
```

## Architecture

| Component | Role |
|-----------|------|
| `desktop/capture` | Full-desktop capture (X11 via `mss`, Wayland via portal + PipeWire/GStreamer) |
| `desktop/webrtc` | `aiortc` peer — desktop is always the **offerer** |
| `desktop/signaling` | JSON WebSocket hub (`offer` / `answer` / `ice` / `ready`) |
| `flutter_app` | Viewer — **answerer**, fullscreen video, FPS/latency overlay, auto-reconnect |

- Video only, default **720p @ 30 FPS**, ~2–4 Mbps (adaptive/max bitrate)
- **One** Android viewer
- **No STUN/TURN** (LAN host candidates only)
- ADB forwards **signaling only**; media uses Wi‑Fi

Protocol details: [`shared/protocol.md`](shared/protocol.md)

## Prerequisites

### Desktop (Ubuntu)

- Python **3.12+**
- FFmpeg / libx264 (for H.264 via PyAV)
- X11 **or** Wayland session

**X11**

```bash
sudo apt install python3-venv python3-pip
```

**Wayland** (additional)

```bash
sudo apt install python3-gi gir1.2-gstreamer-1.0 gstreamer1.0-plugins-base \
  gstreamer1.0-pipewire xdg-desktop-portal
# plus a portal backend, e.g. xdg-desktop-portal-gnome / kde / wlr
```

### Android / Flutter

- Flutter SDK (stable)
- Android device/emulator, **min SDK 24**
- Same Wi‑Fi as the desktop for WebRTC media

## Desktop setup

```bash
cd desktop
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

Useful flags:

```bash
python main.py --port 8080 --width 1280 --height 720 --fps 30 --bitrate 4000000
python main.py --capture x11      # force X11
python main.py --capture wayland  # force Wayland portal
```

On start, the host prints your LAN IP, e.g. `ws://192.168.1.10:8080/ws`.

## Flutter viewer

```bash
cd flutter_app
flutter pub get
flutter run
```

In the app:

1. Enter the desktop **LAN IP** and port `8080`, or enable **USB via ADB reverse**
2. Tap **Connect**
3. When the stream is up, the UI goes fullscreen with an FPS / latency / bitrate overlay

## Networking

### Wi‑Fi (typical)

1. Start `python main.py` on the desktop
2. On the phone, enter the desktop LAN IP → Connect
3. Signaling and media both use the LAN

### USB signaling + Wi‑Fi media

```bash
adb reverse tcp:8080 tcp:8080
```

1. Enable **USB via ADB reverse** in the app (connects to `ws://127.0.0.1:8080/ws`)
2. Keep phone and desktop on the **same Wi‑Fi** so ICE host candidates can carry media

> If the phone has no Wi‑Fi path to the desktop, video will not connect even if signaling works over USB.

## Latency tips

- Prefer wired or strong 5 GHz Wi‑Fi
- Stay at 720p30 for lower encode latency; raise FPS only if the link and CPU allow
- Wayland: approve the portal screen-share prompt promptly; cursor is embedded in the frame
- Desktop and phone should be on the same subnet (no guest Wi‑Fi isolation)

## Development notes

- Signaling message types: `hello`, `ready`, `offer`, `answer`, `ice`, `stats`, `error`, `bye`
- Health check: `http://<desktop>:8080/health`
- Reconnect: the viewer backs off and retries; the host creates a fresh offer when the viewer returns




## notes for to to run the program again: 

cd ~/Desktop/projects/sharing_screen/desktop
source .venv/bin/activate
python main.py



# After running the app into the android 

## optionally I can turn the witch and connect auto:
1. adb reverse tcp:8080 tcp:8080
2. set the UR: in the android screen : 127.0.0.1

then tap on the connect button: 
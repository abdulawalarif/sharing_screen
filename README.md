# sharing_screen

Ubuntu desktop → Android screen mirroring over **WebRTC (H.264)** and a small WebSocket signaling server. Same Wi‑Fi for both devices. Video only, one viewer, LAN only (no STUN/TURN).

```
desktop/       Python host (capture + WebRTC + signaling)
flutter_app/   Flutter Android viewer
shared/        Protocol defaults
```

## Desktop

**Need:** Ubuntu, Python 3.12+, FFmpeg / libx264, X11 or Wayland.

```bash
sudo apt install python3-venv python3-pip
```

Wayland also needs:

```bash
sudo apt install python3-gi gir1.2-gstreamer-1.0 gstreamer1.0-plugins-base \
  gstreamer1.0-pipewire xdg-desktop-portal
```

Then:

```bash
cd desktop
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

The host prints a URL like `ws://192.168.1.10:8080/ws`. Optional:

```bash
python main.py --port 8080 --width 1280 --height 720 --fps 30
python main.py --capture x11      # or: --capture wayland
./start_host.sh                   # ADB reverse (if a phone is plugged in) + host
./install_shortcut.sh             # launcher on ~/Desktop
```

## Flutter app

**Need:** Flutter stable, Android device (min SDK 24), same Wi‑Fi as the desktop.

```bash
cd flutter_app
flutter pub get
flutter run
```

In the app:

1. Enter the desktop **LAN IP** and port `8080`, **or** turn on **USB via ADB reverse**
2. Tap **Connect**
3. Stream goes fullscreen (pinch to zoom)

ADB reverse (signaling only; video still uses Wi‑Fi):

```bash
adb reverse tcp:8080 tcp:8080
```

Then enable **USB via ADB reverse** in the app (`127.0.0.1:8080`). Phone and desktop must stay on the same Wi‑Fi, or video will not connect.

---

Health check: `http://<desktop>:8080/health`. Protocol: [`shared/protocol.md`](shared/protocol.md).

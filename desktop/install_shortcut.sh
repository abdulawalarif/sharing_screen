#!/usr/bin/env bash
# Install a Desktop launcher that points at this checkout (paths resolved here, not committed).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST_DIR="${XDG_DESKTOP_DIR:-$HOME/Desktop}"
DEST="$DEST_DIR/screen-share-host.desktop"

if [[ ! -d "$DEST_DIR" ]]; then
  echo "Desktop folder not found: $DEST_DIR"
  exit 1
fi

cat > "$DEST" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Screen Share Host
Comment=Start Ubuntu→Android screen share (ADB reverse + WebRTC host)
Exec=gnome-terminal --title=ScreenShareHost -- $ROOT/start_host_terminal.sh
Path=$ROOT
Icon=preferences-desktop-display
Terminal=false
Categories=Utility;
StartupNotify=true
EOF

chmod +x "$DEST"
echo "Installed: $DEST"
echo "First time: right-click → Allow Launching (or Run as a Program)."

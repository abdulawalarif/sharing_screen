#!/usr/bin/env bash
# One-shot launcher: ADB reverse (if a device is present) + screen-share host.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${PORT:-8080}"
PYTHON="$ROOT/.venv/bin/python"

if [[ ! -x "$PYTHON" ]]; then
  echo "Missing venv at $ROOT/.venv"
  echo "Run: cd \"$ROOT\" && python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi

if command -v adb >/dev/null 2>&1; then
  if adb devices 2>/dev/null | awk 'NR>1 && $2=="device" {found=1} END{exit !found}'; then
    echo "ADB device found — reversing tcp:${PORT}…"
    adb reverse "tcp:${PORT}" "tcp:${PORT}"
    echo "OK: phone can use 127.0.0.1:${PORT} (USB via ADB reverse)"
  else
    echo "No ADB device connected — skipping reverse (use LAN IP in the app)."
  fi
else
  echo "adb not found — skipping reverse."
fi

if ss -ltn 2>/dev/null | awk -v p=":${PORT}" '$4 ~ p"$" {found=1} END{exit !found}'; then
  echo "Port ${PORT} is already in use."
  echo "Stop the other host first (close its terminal, or: pkill -f 'python main.py'), then try again."
  exit 1
fi

echo "Starting screen-share host on port ${PORT}…"
cd "$ROOT"
exec "$PYTHON" main.py --port "$PORT" "$@"

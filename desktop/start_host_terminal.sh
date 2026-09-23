#!/usr/bin/env bash
# Keep the terminal open after the host exits / errors.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"$ROOT/start_host.sh" "$@"
status=$?

echo
if [[ $status -ne 0 ]]; then
  echo "Host exited with code $status."
fi
read -rp "Press Enter to close…"
exit "$status"

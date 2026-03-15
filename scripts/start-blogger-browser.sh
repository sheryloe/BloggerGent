#!/usr/bin/env bash
set -euo pipefail

BROWSER="${1:-chrome}"
BROWSER_PORT="${BROWSER_PORT:-9222}"
BRIDGE_PORT="${BRIDGE_PORT:-9223}"
START_URL="${START_URL:-https://www.blogger.com}"
PROFILE_DIR="${PROFILE_DIR:-$(cd "$(dirname "$0")/.." && pwd)/storage/playwright-browser}"

mkdir -p "$PROFILE_DIR"

if [[ "$BROWSER" == "edge" ]]; then
  if command -v microsoft-edge >/dev/null 2>&1; then
    BROWSER_BIN="$(command -v microsoft-edge)"
  elif command -v microsoft-edge-stable >/dev/null 2>&1; then
    BROWSER_BIN="$(command -v microsoft-edge-stable)"
  else
    echo "Could not find Microsoft Edge." >&2
    exit 1
  fi
else
  if command -v google-chrome >/dev/null 2>&1; then
    BROWSER_BIN="$(command -v google-chrome)"
  elif command -v chromium >/dev/null 2>&1; then
    BROWSER_BIN="$(command -v chromium)"
  else
    echo "Could not find Chrome or Chromium." >&2
    exit 1
  fi
fi

"$BROWSER_BIN" \
  --remote-debugging-port="$BROWSER_PORT" \
  --remote-debugging-address=0.0.0.0 \
  --user-data-dir="$PROFILE_DIR" \
  "$START_URL" >/dev/null 2>&1 &

python3 "$(cd "$(dirname "$0")" && pwd)/browser_cdp_bridge.py" \
  --listen-port "$BRIDGE_PORT" \
  --target-port "$BROWSER_PORT" >/dev/null 2>&1 &

echo
echo "Started $BROWSER with remote debugging."
echo "Profile dir : $PROFILE_DIR"
echo "Browser CDP : http://127.0.0.1:$BROWSER_PORT"
echo "Bridge CDP  : http://host.docker.internal:$BRIDGE_PORT"
echo "Next step   : sign into Blogger once in that browser window."

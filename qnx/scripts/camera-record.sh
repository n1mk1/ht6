#!/usr/bin/env bash
# Record a short clip on the Pi (headless proof the camera streams to disk).
# Usage: ./scripts/camera-record.sh [seconds]   (default 5)
set -uo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
source "$HERE/env.sh"
SECS="${1:-5}"
echo "Recording ${SECS}s from CAMERA_UNIT_1 ..."
# Drive the example's start/stop keypresses over a pty with timed newlines.
( sleep 2; printf '\r'; sleep "$SECS"; printf '\r'; sleep 1 ) \
  | ssh -tt $SSH_OPTS "$PI_USER@$PI_HOST" \
      'cd /data/share/sensor && camera_example4_record -u 1 -t NV12' 2>&1 | _strip_pq
echo "--- newest clip on Pi ---"
ssh $SSH_OPTS "$PI_USER@$PI_HOST" 'ls -la $(ls -t /data/share/sensor/*.mp4 | head -1)' 2>&1 | _strip_pq

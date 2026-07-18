#!/usr/bin/env bash
# Launch the live camera viewfinder ON the Pi's screen (visible via TigerVNC).
# The QNX camera examples render to /dev/screen regardless of where launched,
# so this shows up on the weston desktop you see over VNC.
set -uo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
source "$HERE/env.sh"
echo "Starting viewfinder on the Pi — look at your TigerVNC window."
echo "Ctrl-C here to stop."
# -tt allocates a pty so the example's keypress-read works; runs until killed.
ssh -tt $SSH_OPTS "$PI_USER@$PI_HOST" 'camera_example3_viewfinder -u 1' 2>&1 | _strip_pq

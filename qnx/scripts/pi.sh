#!/usr/bin/env bash
# Run a command on the Pi from the synced project dir. e.g. ./scripts/pi.sh 'ls -la'
set -uo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
source "$HERE/env.sh"
ssh $SSH_OPTS "$PI_USER@$PI_HOST" "cd $PI_DIR 2>/dev/null; $*" 2>&1 | _strip_pq

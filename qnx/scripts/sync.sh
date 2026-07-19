#!/usr/bin/env bash
# Push local qnx/ code to the Pi over rsync. Fast, run on every change.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
source "$HERE/env.sh"

ssh $SSH_OPTS "$PI_USER@$PI_HOST" "mkdir -p $PI_DIR" 2>/dev/null | _strip_pq || true
rsync -az --delete \
  --exclude '.git' --exclude 'build/' --exclude '__pycache__/' --exclude '*.mp4' \
  --exclude '*.pyc' \
  `# Pi-side generated artifacts — never clobber/delete on sync:` \
  --exclude 'rt_vision' --exclude 'sessions/' --exclude 'outbox/' \
  --exclude 'datasets/image_quality/data/' \
  --exclude 'models/' --exclude 'vendor/' \
  --exclude 'device.env' \
  --exclude 'server.log' --exclude 'server.pid' \
  -e "ssh $SSH_OPTS" \
  "$HERE/" "$PI_USER@$PI_HOST:$PI_DIR/"
echo "synced -> $PI_USER@$PI_HOST:$PI_DIR"

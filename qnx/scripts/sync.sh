#!/usr/bin/env bash
# Push local qnx/ code to the Pi over rsync. Fast, run on every change.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
source "$HERE/env.sh"

ssh $SSH_OPTS "$PI_USER@$PI_HOST" "mkdir -p $PI_DIR" 2>/dev/null | _strip_pq || true
rsync -az --delete \
  --exclude '.git' --exclude 'build/' --exclude '__pycache__/' --exclude '*.mp4' \
  -e "ssh $SSH_OPTS" \
  "$HERE/" "$PI_USER@$PI_HOST:$PI_DIR/"
echo "synced -> $PI_USER@$PI_HOST:$PI_DIR"

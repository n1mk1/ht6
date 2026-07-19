#!/usr/bin/env bash
# Copy camera-generated training data from the Pi into the local repository.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
source "$HERE/env.sh"

DEST="$HERE/datasets/image_quality/data"
mkdir -p "$DEST"
rsync -az \
  -e "ssh $SSH_OPTS" \
  "$PI_USER@$PI_HOST:$PI_DIR/datasets/image_quality/data/" "$DEST/"
echo "dataset copied -> $DEST"

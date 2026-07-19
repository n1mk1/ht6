#!/usr/bin/env bash
# Verify and copy GGUF model artifacts separately from the normal dev sync.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
source "$HERE/env.sh"

MODEL="$HERE/models/SmolVLM-256M-Instruct-Q8_0.gguf"
MMPROJ="$HERE/models/mmproj-SmolVLM-256M-Instruct-Q8_0.gguf"
test -f "$MODEL"
test -f "$MMPROJ"

MODEL_SHA="$(shasum -a 256 "$MODEL" | awk '{print $1}')"
MMPROJ_SHA="$(shasum -a 256 "$MMPROJ" | awk '{print $1}')"
test "$MODEL_SHA" = "2a31195d3769c0b0fd0a4906201666108834848db768af11de1d2cef7cd35e65"
test "$MMPROJ_SHA" = "7e943f7c53f0382a6fc41b6ee0c2def63ba4fded9ab8ed039cc9e2ab905e0edd"

ssh $SSH_OPTS "$PI_USER@$PI_HOST" "mkdir -p $PI_DIR/models"
rsync -az --partial -e "ssh $SSH_OPTS" "$MODEL" "$MMPROJ" \
  "$PI_USER@$PI_HOST:$PI_DIR/models/"
echo "AI models copied -> $PI_USER@$PI_HOST:$PI_DIR/models"


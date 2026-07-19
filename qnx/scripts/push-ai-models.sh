#!/usr/bin/env bash
# Verify and copy GGUF model artifacts separately from the normal dev sync.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
source "$HERE/env.sh"

MODEL="$HERE/models/SmolVLM-256M-Instruct-Q8_0.gguf"
MMPROJ="$HERE/models/mmproj-SmolVLM-256M-Instruct-Q8_0.gguf"
SUMMARY_MODEL="$HERE/models/qwen2.5-0.5b-instruct-q4_k_m.gguf"
test -f "$MODEL"
test -f "$MMPROJ"
test -f "$SUMMARY_MODEL"

MODEL_SHA="$(shasum -a 256 "$MODEL" | awk '{print $1}')"
MMPROJ_SHA="$(shasum -a 256 "$MMPROJ" | awk '{print $1}')"
SUMMARY_SHA="$(shasum -a 256 "$SUMMARY_MODEL" | awk '{print $1}')"
test "$MODEL_SHA" = "2a31195d3769c0b0fd0a4906201666108834848db768af11de1d2cef7cd35e65"
test "$MMPROJ_SHA" = "7e943f7c53f0382a6fc41b6ee0c2def63ba4fded9ab8ed039cc9e2ab905e0edd"
test "$SUMMARY_SHA" = "74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db"

ssh $SSH_OPTS "$PI_USER@$PI_HOST" "mkdir -p $PI_DIR/models"
rsync -az --partial -e "ssh $SSH_OPTS" "$MODEL" "$MMPROJ" "$SUMMARY_MODEL" \
  "$PI_USER@$PI_HOST:$PI_DIR/models/"
echo "AI models copied -> $PI_USER@$PI_HOST:$PI_DIR/models"

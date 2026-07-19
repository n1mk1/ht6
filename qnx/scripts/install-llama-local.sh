#!/usr/bin/env bash
# Run on the QNX target. Installs official QNX APKs without requiring root.
set -u

BASE="${PRAXIS_BASE:-$HOME/steadyeye}"
ROOT="$BASE/vendor/qnx-root"
mkdir -p "$ROOT"

# Protected base-QNX files cannot be recreated by an unprivileged user. The
# target already provides them; apk may report those extraction errors while
# still installing all llama/OpenBLAS files into this application-owned root.
apk --root "$ROOT" \
  --repositories-file /etc/apk/repositories \
  --keys-dir /etc/apk/keys \
  --no-logfile add --initdb --usermode --no-scripts \
  bash qnx-crypto-openssl3 llama.cpp llama.cpp-extras llama.cpp-libs || true

LIBS="$ROOT/usr/lib/llama.cpp:$ROOT/usr/lib:/usr/lib:/lib"
if ! env LD_LIBRARY_PATH="$LIBS" "$ROOT/usr/bin/llama-cli" --version; then
  echo "llama.cpp installation did not produce a runnable QNX binary" >&2
  exit 1
fi
if ! env LD_LIBRARY_PATH="$LIBS" "$ROOT/usr/bin/llama-completion" --version; then
  echo "llama.cpp completion executable is missing" >&2
  exit 1
fi
if ! test -x "$ROOT/usr/bin/llama-mtmd-cli"; then
  echo "multimodal llama executable is missing" >&2
  exit 1
fi
echo "QNX llama.cpp app-local installation ready: $ROOT"

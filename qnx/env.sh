# Shared connection settings for the QNX Pi. Sourced by the scripts.
# Change PI_HOST if the Pi's hostname/IP changes (e.g. different network).
PI_HOST="${PI_HOST:-qnxpi23.local}"
PI_USER="${PI_USER:-qnxuser}"
PI_KEY="${PI_KEY:-$HOME/.ssh/qnxpi}"
PI_DIR="${PI_DIR:-/data/home/qnxuser/steadyeye}"   # where code is synced ON the Pi
PI_PY="${PI_PY:-/data/home/qnxuser/venv/bin/python}" # venv python (has mpu6050 pkg)

SSH_OPTS="-i $PI_KEY -o IdentitiesOnly=yes -o ConnectTimeout=12"

# Strip the harmless post-quantum SSH warning lines from remote output.
_strip_pq() { grep -v "post-quantum\|store now\|may need to be upgraded\|WARNING: connection\|This session"; }

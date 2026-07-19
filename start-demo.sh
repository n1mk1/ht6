#!/usr/bin/env bash
# Praxis demo launcher — one command to bring the whole stack up (or down).
#
#   ./start-demo.sh          start/restart everything, then print a status board
#   ./start-demo.sh stop     stop the local services (leaves the Pi server running)
#
# Pieces managed:
#   backend   FastAPI + MongoDB Atlas          :8000  (binds 0.0.0.0 so the Pi can reach it)
#   frontend  Vite React dashboard             :5173+ (vite picks the next free port)
#   assistant Gemini UI assistant              :8002
#   copilot   Therapist copilot                :8003
#   qnx       steadyeye server on the Pi       qnxpi23.local:8080 (via ssh; needs same network)
#
# Logs: /tmp/praxis-demo-logs/*.log

set -u
ROOT="$(cd "$(dirname "$0")" && pwd)"
LOGS=/tmp/praxis-demo-logs
mkdir -p "$LOGS"

PI_HOST="${PI_HOST:-qnxpi23.local}"
PI_KEY="${PI_KEY:-$HOME/.ssh/qnxpi}"
PI_DIR=/data/home/qnxuser/steadyeye
PI_PY=/data/home/qnxuser/venv/bin/python

say()  { printf '\033[1m%s\033[0m\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }

kill_local() {
  pkill -f "uvicorn praxis_api.main" 2>/dev/null
  pkill -f "server.main:app --host 0.0.0.0 --port 8002" 2>/dev/null
  pkill -f "server.main:app --host 0.0.0.0 --port 8003" 2>/dev/null
  pkill -f "$ROOT/frontend/node_modules/.bin/vite" 2>/dev/null
  pkill -f "$ROOT/frontend/node_modules/vite" 2>/dev/null
  sleep 1
}

if [[ "${1:-}" == "stop" ]]; then
  say "Stopping local Praxis services..."
  kill_local
  ok "backend, frontend, assistant, copilot stopped (Pi server left running)"
  exit 0
fi

say "Restarting local Praxis services..."
kill_local

# --- backend :8000 (0.0.0.0 so the Pi can reach it) -------------------------
(cd "$ROOT/backend" && nohup .venv/bin/python -m uvicorn praxis_api.main:app \
  --host 0.0.0.0 --port 8000 > "$LOGS/backend.log" 2>&1 &)

# --- AI teammates :8002 / :8003 ---------------------------------------------
(cd "$ROOT/gemini-ui-assistant" && nohup "$ROOT/.venv-ai/bin/uvicorn" server.main:app \
  --host 0.0.0.0 --port 8002 > "$LOGS/assistant.log" 2>&1 &)
(cd "$ROOT/therapist-copilot" && BACKEND_URL=http://127.0.0.1:8000 nohup "$ROOT/.venv-ai/bin/uvicorn" server.main:app \
  --host 0.0.0.0 --port 8003 > "$LOGS/copilot.log" 2>&1 &)

# --- frontend (vite picks 5173 or next free) ---------------------------------
(cd "$ROOT/frontend" && nohup npm run dev > "$LOGS/frontend.log" 2>&1 &)

# --- QNX Pi server ------------------------------------------------------------
say "Checking QNX Pi ($PI_HOST)..."
if curl -s -m 4 "http://$PI_HOST:8080/api/state" > /dev/null 2>&1; then
  ok "Pi server already running on :8080 — leaving it alone"
  PI_UP=1
elif [[ -f "$PI_KEY" ]] && ssh -T -i "$PI_KEY" -o IdentitiesOnly=yes -o ConnectTimeout=6 \
      "qnxuser@$PI_HOST" true 2>/dev/null; then
  say "Starting Pi server via ssh..."
  ssh -T -i "$PI_KEY" -o IdentitiesOnly=yes -o ConnectTimeout=8 "qnxuser@$PI_HOST" "
    cd $PI_DIR || exit 1
    kill \"\$(cat server.pid 2>/dev/null)\" 2>/dev/null; sleep 2
    set -a; . ./device.env 2>/dev/null; set +a
    nohup $PI_PY server/server.py > server.log 2>&1 &
    echo \$! > server.pid" 2>/dev/null
  sleep 3
  curl -s -m 4 "http://$PI_HOST:8080/api/state" > /dev/null 2>&1 && PI_UP=1 || PI_UP=0
else
  PI_UP=0
fi

# --- wait for local services ---------------------------------------------------
printf 'Waiting for local services'
for _ in $(seq 1 20); do
  printf '.'
  curl -s -m 1 http://127.0.0.1:8000/api/v1/health > /dev/null 2>&1 && break
  sleep 1
done
echo
sleep 2

# --- status board ---------------------------------------------------------------
say ""
say "=== Praxis demo status ==="

if curl -s -m 3 http://127.0.0.1:8000/api/v1/health | grep -q '"ok"'; then
  if curl -s -m 8 http://127.0.0.1:8000/api/v1/users > /dev/null 2>&1; then
    ok "backend   :8000  up + MongoDB Atlas reachable"
  else
    warn "backend   :8000  up but Atlas NOT reachable (IP allowlist? network?) — see $LOGS/backend.log"
  fi
else
  bad "backend   :8000  DOWN — see $LOGS/backend.log"
fi

FRONT_URL=$(grep -oE 'http://localhost:[0-9]+/' "$LOGS/frontend.log" 2>/dev/null | head -1)
for _ in $(seq 1 10); do
  [[ -n "$FRONT_URL" ]] && break
  sleep 1
  FRONT_URL=$(grep -oE 'http://localhost:[0-9]+/' "$LOGS/frontend.log" 2>/dev/null | head -1)
done
if [[ -n "$FRONT_URL" ]]; then
  ok "frontend  $FRONT_URL  <-- open this and log in"
else
  bad "frontend  not up yet — see $LOGS/frontend.log"
fi

if curl -s -m 3 http://127.0.0.1:8002/assistant-api/health | grep -q '"ok"'; then
  MOCK=$(curl -s -m 3 http://127.0.0.1:8002/assistant-api/health | grep -o '"mock_mode":[a-z]*')
  ok "assistant :8002  up ($MOCK)"
else
  bad "assistant :8002  DOWN — see $LOGS/assistant.log"
fi

if curl -s -m 3 http://127.0.0.1:8003/copilot-api/health | grep -q '"ok"'; then
  MOCK=$(curl -s -m 3 http://127.0.0.1:8003/copilot-api/health | grep -o '"mock_mode":[a-z]*')
  ok "copilot   :8003  up ($MOCK)"
else
  bad "copilot   :8003  DOWN — see $LOGS/copilot.log"
fi

if [[ "$PI_UP" == 1 ]]; then
  OUTBOX=$(curl -s -m 4 "http://$PI_HOST:8080/api/outbox/status" 2>/dev/null)
  if echo "$OUTBOX" | grep -q '"backend_configured": true'; then
    ok "qnx pi    $PI_HOST:8080  up, backend wired"
  else
    warn "qnx pi    $PI_HOST:8080  up but BACKEND_URL not configured (check $PI_DIR/device.env)"
  fi
else
  warn "qnx pi    $PI_HOST unreachable — are you on the Pi's hotspot? (dashboard still works without it)"
fi

say ""
say "Logs: $LOGS/   ·   Stop local services: ./start-demo.sh stop"

#!/usr/bin/env bash
# Sends the #44815 request through a real LiteLLM proxy and prints the HTTP status,
# the x-litellm-* response headers and how many calls each fake provider received.
# Usage: bash proxy/demo.sh <venv dir> <config file> <label>
# Needs the two fake providers on :9101 and :9102 (run_all.sh starts them).
set -euo pipefail
VENV="$1"
CONFIG="$2"
LABEL="$3"
PORT="${PROXY_PORT:-4000}"
export LITELLM_MASTER_KEY="${LITELLM_MASTER_KEY:-sk-repro-kit-local-only}"
export LITELLM_LOCAL_MODEL_COST_MAP=True
mkdir -p results
LOG="results/proxy_${LABEL}.log"
BODY="results/proxy_${LABEL}_body.json"

"$VENV/bin/litellm" --config "$CONFIG" --port "$PORT" > "$LOG" 2>&1 &
PID=$!
trap 'kill $PID 2>/dev/null || true; wait $PID 2>/dev/null || true' EXIT

for _ in $(seq 1 120); do
  if curl -fs "http://127.0.0.1:$PORT/health/liveliness" > /dev/null 2>&1; then break; fi
  if ! kill -0 "$PID" 2>/dev/null; then echo "proxy exited at startup, see $LOG"; tail -n 30 "$LOG"; exit 1; fi
  sleep 1
done

curl -fs -X POST http://127.0.0.1:9101/reset > /dev/null
curl -fs -X POST http://127.0.0.1:9102/reset > /dev/null

VERSION="$("$VENV/bin/python" -c 'import importlib.metadata as m; print(m.version("litellm"))')"
echo "### $LABEL (LiteLLM $VERSION, $CONFIG)"
HEADERS="$(curl -s -D - -o "$BODY" "http://127.0.0.1:$PORT/v1/chat/completions" \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" -H "Content-Type: application/json" \
  -d '{"model": "primary", "messages": [{"role": "user", "content": "one word please"}]}')"
echo "$HEADERS" | head -n 1 | tr -d '\r'
echo "$HEADERS" | grep -i -E '^x-litellm-(model-group|attempted-fallbacks|attempted-retries|max-retries|model-api-base)' | tr -d '\r' || true
echo "body: $(head -c 240 "$BODY")"
echo "calls to primary: $(curl -fs http://127.0.0.1:9101/stats | "$VENV/bin/python" -c 'import json,sys; print(json.load(sys.stdin)["attempts"])')"
echo "calls to backup:  $(curl -fs http://127.0.0.1:9102/stats | "$VENV/bin/python" -c 'import json,sys; print(json.load(sys.stdin)["attempts"])')"
echo

#!/usr/bin/env bash
# Runs every repro end to end and writes results/SUMMARY.md.
# Takes about 7 minutes, plus a few minutes the first time to install dependencies.
#   ./run_all.sh            stable LiteLLM 1.105.1, plus the 1.107.0.dev3 comparison for #44815
#   WITH_DEV=0 ./run_all.sh  skip the 1.107.0.dev3 comparison
#   WITH_PROXY=0 ./run_all.sh skip the proxy demo
set -euo pipefail
cd "$(dirname "$0")"

PY="${PY:-python3}"
WITH_DEV="${WITH_DEV:-1}"
WITH_PROXY="${WITH_PROXY:-1}"
export LITELLM_LOCAL_MODEL_COST_MAP=True   # don't fetch the model price map over the network

# The proxy's scheduler crashes at startup when TZ names the legacy alias Asia/Calcutta and the
# machine's tz database lacks it (common in slim containers). Asia/Kolkata is the same zone.
if [ "${TZ:-}" = "Asia/Calcutta" ]; then export TZ=Asia/Kolkata; fi

make_venv () {  # $1 dir, $2 litellm pin
  if [ ! -x "$1/bin/python" ]; then
    if command -v uv > /dev/null 2>&1; then
      uv venv "$1" -q --python "$PY"
      uv pip install --python "$1/bin/python" -q --prerelease=allow "litellm[proxy]==$2" fastapi uvicorn httpx
    else
      "$PY" -m venv "$1"
      "$1/bin/pip" install -q --upgrade pip
      "$1/bin/pip" install -q --pre "litellm[proxy]==$2" fastapi uvicorn httpx
    fi
  fi
}

echo "== setting up environments"
make_venv .venv 1.105.1
if [ "$WITH_DEV" = "1" ]; then make_venv .venv-dev 1.107.0.dev3; fi
mkdir -p results

echo "== starting fake providers on :9101 (primary) and :9102 (backup)"
.venv/bin/python fake_provider.py --name primary --port 9101 > results/provider_primary.log 2>&1 &
P1=$!
.venv/bin/python fake_provider.py --name backup --port 9102 > results/provider_backup.log 2>&1 &
P2=$!
trap 'kill $P1 $P2 2>/dev/null || true' EXIT
for _ in $(seq 1 40); do
  curl -fs http://127.0.0.1:9101/stats > /dev/null 2>&1 && curl -fs http://127.0.0.1:9102/stats > /dev/null 2>&1 && break
  sleep 0.5
done

echo "== #40405: single deployment cooldown (about 5 minutes)"
.venv/bin/python repro_40405_single_deployment_cooldown.py

echo "== cooldown rule checks"
.venv/bin/python check_cooldown_rules.py

echo "== #44815: silent fallback on a rejected param"
.venv/bin/python repro_44815_silent_fallback.py
if [ "$WITH_DEV" = "1" ]; then .venv-dev/bin/python repro_44815_silent_fallback.py; fi

if [ "$WITH_PROXY" = "1" ]; then
  echo "== proxy demo"
  {
    bash proxy/demo.sh .venv proxy/config.yaml stable_default
    if [ "$WITH_DEV" = "1" ]; then bash proxy/demo.sh .venv-dev proxy/config_fail_loudly.yaml dev_fail_loudly; fi
  } | tee results/proxy_demo.txt
fi

echo "== summary"
.venv/bin/python summarize.py

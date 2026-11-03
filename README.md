# litellm-router-repros

Quick scripts I put together to test a couple of LiteLLM router issues locally (#40405 and #44815) using a mock FastAPI server instead of hitting real APIs.

## Running it

Needs Python 3.10+ and ports 9101, 9102, 4000 free.

    ./run_all.sh

This sets up the venv, spins up `fake_provider.py`, runs the test scripts, and saves the raw outputs in `results/`.

## What I found (on v1.105.1)

**#40405 (single deployment cooldowns)**
If a model group only has 1 deployment, the router doesn't cool it down on 503s or 429s by default. So during an outage, every request still wastes 3 attempts (~4.5s) on the dead primary before switching to the fallback.
- Setting `allowed_fails=3` on the router does nothing because 3 is already the default in code, so the check ignores it.
- Setting `allowed_fails=1` under `model_info` also gets skipped for single-deployment groups.
- What works: setting `allowed_fails=1` and `cooldown_time=30` in `router_settings` (or using `allowed_fails_policy` on the deployment). That cools it down after the 2nd fail and drops primary attempts to 0.31/req (~0.01s).

**#44815 (silent fallback on unsupported params)**
On 1.105.1, passing an unsupported param like `reasoning_effort="xhigh"` silently falls back to the backup model and returns 200 OK (`x-litellm-attempted-fallbacks: 1`).
Tested against `1.107.0.dev3` (which has PR #46350) with `fallback_on_unsupported_params: false` and confirmed it returns a 400 error right away without calling the backup.

**Ubuntu 24.04 timezone crash**
While running the proxy demo on Ubuntu 24.04, `litellm --config` crashed on startup because my system had `TZ=Asia/Calcutta` and `pip install litellm[proxy]` doesn't install `tzdata`. Installing `tzdata` or switching `TZ=Asia/Kolkata` fixes it.

"""Quick checks of when the Router cools a deployment down, with LiteLLM defaults.

Each check sends a handful of requests with num_retries=0 and counts how many
reached deployment A (port 9101). If A had been cooled down after its first
failure, it would see exactly 1 attempt.

In the two-deployment checks A has `order: 1` and B `order: 2`, so the router
always picks A while A is in rotation. That keeps the counts deterministic:
without it, simple-shuffle picks A or B at random and the numbers vary per run.

  429_single : model group with ONE deployment (A) returning 429
  429_multi  : model group with TWO deployments, A returns 429, B is healthy
  timeout_multi : TWO deployments, A answers after 3 s with timeout=1 s (408), B healthy
  401_single : model group with ONE deployment (A) returning 401 (non-retryable)

Usage: python check_cooldown_rules.py   (fake providers must be running)
"""

from __future__ import annotations

import json
from importlib.metadata import version
from pathlib import Path

import httpx
import litellm
from litellm import Router

A = "http://127.0.0.1:9101"
B = "http://127.0.0.1:9102"
REQUESTS = 6


def deployment(base: str, order: int | None = None) -> dict:
    params: dict = {"model": "openai/fake-model", "api_base": f"{base}/v1", "api_key": "sk-fake"}
    if order is not None:
        params["order"] = order  # lower order is preferred while it is healthy
    return {"model_name": "group", "litellm_params": params}


def run(label: str, model_list: list, a_mode: dict, timeout: float = 30) -> dict:
    with httpx.Client() as http:
        for base in (A, B):
            http.post(f"{base}/reset")
            http.post(f"{base}/control", json={"mode": "ok"})
        http.post(f"{A}/control", json=a_mode)
    router = Router(model_list=model_list, num_retries=0, timeout=timeout)
    outcomes = []
    for _ in range(REQUESTS):
        try:
            r = router.completion(model="group", messages=[{"role": "user", "content": "ping"}])
            outcomes.append(r.choices[0].message.content.replace("answered by ", ""))
        except Exception as exc:  # noqa: BLE001
            outcomes.append(type(exc).__name__)
    with httpx.Client() as http:
        a_attempts = http.get(f"{A}/stats").json()["attempts"]
        http.post(f"{A}/control", json={"mode": "ok"})
    return {"check": label, "requests": REQUESTS, "attempts_on_A": a_attempts, "cooled_down_after_first_failure": a_attempts == 1, "outcomes": outcomes}


def main() -> None:
    litellm.suppress_debug_info = True
    results = [
        run("429_single", [deployment(A)], {"mode": "429", "retry_after": 1}),
        run("429_multi", [deployment(A, 1), deployment(B, 2)], {"mode": "429", "retry_after": 1}),
        run("timeout_multi", [deployment(A, 1), deployment(B, 2)], {"mode": "slow", "delay": 3}, timeout=1),
        run("401_single", [deployment(A)], {"mode": "error", "status": 401}),
    ]
    out = {"litellm_version": version("litellm"), "results": results}
    print(json.dumps(out, indent=2))
    Path("results").mkdir(exist_ok=True)
    Path("results/check_cooldown_rules.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()

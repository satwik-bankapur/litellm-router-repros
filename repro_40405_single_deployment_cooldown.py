"""Repro for BerriAI/litellm#40405: a single deployment plus a fallback never cools down.

Scenario (scaled down from the issue's Failover Bench S15 run):
  - model group "primary" has ONE deployment, "backup" has one deployment
  - fallbacks: primary -> backup, num_retries: 2, timeout: 30
  - the primary returns 503 for OUTAGE_S seconds, then recovers
  - one request every GAP_S seconds during the outage, then a few after it

Variants:
  default           no allowed_fails / cooldown_time set
  tuned             router-level allowed_fails=1, cooldown_time=30   (the issue's fix)
  explicit_default  router-level allowed_fails=3 (equal to LiteLLM's default)
  deployment_level  allowed_fails=1, cooldown_time=30 under the primary's model_info
  deployment_policy allowed_fails_policy {ServiceUnavailableErrorAllowedFails: 1} under model_info

Usage: python repro_40405_single_deployment_cooldown.py [variant ...]
Needs the two fake providers running (see run_all.sh).
"""

from __future__ import annotations

import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

import httpx
import litellm
from litellm import Router

PRIMARY = "http://127.0.0.1:9101"
BACKUP = "http://127.0.0.1:9102"
OUTAGE_S = 40
GAP_S = 3
AFTER_OUTAGE_REQUESTS = 3

# Router-level settings per variant.
VARIANTS: dict[str, dict] = {
    "default": {},
    "tuned": {"allowed_fails": 1, "cooldown_time": 30},
    "explicit_default": {"allowed_fails": 3},
    "deployment_level": {},
    "deployment_policy": {},
}
# Deployment-level settings (the primary's model_info) per variant.
PRIMARY_MODEL_INFO: dict[str, dict] = {
    "deployment_level": {"allowed_fails": 1, "cooldown_time": 30},
    "deployment_policy": {"allowed_fails_policy": {"ServiceUnavailableErrorAllowedFails": 1}, "cooldown_time": 30},
}


def make_router(name: str) -> Router:
    model_list = [
        {
            "model_name": "primary",
            "litellm_params": {"model": "openai/fake-model", "api_base": f"{PRIMARY}/v1", "api_key": "sk-fake"},
            "model_info": PRIMARY_MODEL_INFO.get(name, {}),
        },
        {
            "model_name": "backup",
            "litellm_params": {"model": "openai/fake-model", "api_base": f"{BACKUP}/v1", "api_key": "sk-fake"},
        },
    ]
    return Router(
        model_list=model_list, num_retries=2, timeout=30, fallbacks=[{"primary": ["backup"]}], **VARIANTS[name]
    )


async def run_variant(name: str) -> dict:
    router = make_router(name)
    async with httpx.AsyncClient() as http:
        for base in (PRIMARY, BACKUP):
            await http.post(f"{base}/reset")
            await http.post(f"{base}/control", json={"mode": "ok"})
        await http.post(f"{PRIMARY}/control", json={"mode": "503", "seconds": OUTAGE_S})
        start = time.time()

        rows = []
        while time.time() - start < OUTAGE_S:
            rows.append(await one_request(router, http, start, phase="outage"))
            await asyncio.sleep(GAP_S)
        # let the outage end, then show recovery
        await asyncio.sleep(max(0.0, start + OUTAGE_S + 1 - time.time()))
        for _ in range(AFTER_OUTAGE_REQUESTS):
            rows.append(await one_request(router, http, start, phase="recovered"))
            await asyncio.sleep(GAP_S)

    outage = [r for r in rows if r["phase"] == "outage"]
    outage_latency = [r["latency_s"] for r in outage]
    primary_attempts_in_outage = sum(r["primary_attempts"] for r in outage)
    return {
        "variant": name,
        "router_settings": VARIANTS[name] or "none",
        "primary_model_info": PRIMARY_MODEL_INFO.get(name) or "none",
        "outage_requests": len(outage),
        "outage_served": sum(1 for r in outage if r["ok"]),
        "outage_latency_median_s": round(statistics.median(outage_latency), 2),
        "outage_latency_max_s": round(max(outage_latency), 2),
        "primary_attempts_during_outage": primary_attempts_in_outage,
        "primary_attempts_per_outage_request": round(primary_attempts_in_outage / len(outage), 2),
        "primary_attempts_by_outage_request": [r["primary_attempts"] for r in outage],
        "served_by_after_outage": [r["served_by"] for r in rows if r["phase"] == "recovered"],
        "requests": rows,
    }


async def one_request(router: Router, http: httpx.AsyncClient, start: float, phase: str) -> dict:
    """Send one request; requests are sequential, so the primary's call count delta is this request's."""
    before = (await http.get(f"{PRIMARY}/stats")).json()["attempts"]
    t0 = time.time()
    ok, served_by, error = True, None, None
    try:
        response = await router.acompletion(model="primary", messages=[{"role": "user", "content": "ping"}])
        served_by = response.choices[0].message.content.replace("answered by ", "")
    except Exception as exc:  # noqa: BLE001 - we want to record any failure
        ok, error = False, f"{type(exc).__name__}: {str(exc)[:120]}"
    latency = time.time() - t0
    after = (await http.get(f"{PRIMARY}/stats")).json()["attempts"]
    return {
        "phase": phase,
        "sent_at_s": round(t0 - start, 1),
        "latency_s": round(latency, 2),
        "primary_attempts": after - before,
        "ok": ok,
        "served_by": served_by,
        "error": error,
    }


async def main() -> None:
    litellm.suppress_debug_info = True
    names = sys.argv[1:] or list(VARIANTS)
    results = []
    for name in names:
        print(f"--- running variant: {name}", flush=True)
        result = await run_variant(name)
        summary = {k: v for k, v in result.items() if k != "requests"}
        print(json.dumps(summary, indent=2), flush=True)
        results.append(result)
    out = Path("results") / "repro_40405.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"litellm_version": litellm_version(), "results": results}, indent=2))
    print(f"wrote {out}")


def litellm_version() -> str:
    from importlib.metadata import version

    return version("litellm")


if __name__ == "__main__":
    asyncio.run(main())

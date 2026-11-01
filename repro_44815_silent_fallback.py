"""Repro for BerriAI/litellm#44815: a config error hides behind a 200 from the fallback.

The primary deployment rejects a request parameter before anything is sent
(UnsupportedParamsError for reasoning_effort="xhigh" on an unmapped gpt-5 model).
With a fallback configured, LiteLLM answers from the backup instead of surfacing the error.

  - On v1.105.1 (latest stable) this always happens; there is no switch.
  - From v1.107 (BerriAI/litellm#46350, merged Oct 14 2026), router setting
    fallback_on_unsupported_params=False raises the error instead.

Usage: python repro_44815_silent_fallback.py
Needs the two fake providers running (see run_all.sh).
"""

from __future__ import annotations

import json
import sys
from importlib.metadata import version
from pathlib import Path

import httpx
import litellm
from litellm import Router

PRIMARY = "http://127.0.0.1:9101"
BACKUP = "http://127.0.0.1:9102"
UNSUPPORTED = {"reasoning_effort": "xhigh"}


def make_router(**settings) -> Router:
    model_list = [
        {
            "model_name": "primary",
            "litellm_params": {"model": "openai/gpt-5-unmapped", "api_base": f"{PRIMARY}/v1", "api_key": "sk-fake"},
        },
        {
            "model_name": "backup",
            "litellm_params": {"model": "openai/fake-model", "api_base": f"{BACKUP}/v1", "api_key": "sk-fake"},
        },
    ]
    return Router(model_list=model_list, num_retries=0, fallbacks=[{"primary": ["backup"]}], **settings)


def run_case(label: str, **settings) -> dict:
    with httpx.Client() as http:
        for base in (PRIMARY, BACKUP):
            http.post(f"{base}/reset")
            http.post(f"{base}/control", json={"mode": "ok"})
    try:
        router = make_router(**settings)
    except TypeError as exc:
        return {"case": label, "settings": settings, "outcome": "setting not accepted by this version", "detail": str(exc)[:160]}

    outcome: dict = {"case": label, "settings": settings or "none (LiteLLM defaults)"}
    try:
        response = router.completion(model="primary", messages=[{"role": "user", "content": "one word please"}], **UNSUPPORTED)
        headers = (getattr(response, "_hidden_params", {}) or {}).get("additional_headers", {}) or {}
        outcome.update(
            outcome="200 OK",
            served_by=response.choices[0].message.content.replace("answered by ", ""),
            attempted_fallbacks=headers.get("x-litellm-attempted-fallbacks"),
        )
    except Exception as exc:  # noqa: BLE001
        outcome.update(outcome=f"raised {type(exc).__name__}", detail=str(exc).splitlines()[0][:160])
    with httpx.Client() as http:
        outcome["primary_calls"] = http.get(f"{PRIMARY}/stats").json()["attempts"]
        outcome["backup_calls"] = http.get(f"{BACKUP}/stats").json()["attempts"]
    return outcome


def main() -> None:
    litellm.suppress_debug_info = True
    v = version("litellm")
    cases = [run_case("default")]
    cases.append(run_case("fallback_on_unsupported_params=False", fallback_on_unsupported_params=False))
    result = {"litellm_version": v, "cases": cases}
    print(json.dumps(result, indent=2))
    out = Path("results") / f"repro_44815_litellm_{v}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(result, indent=2))
    print(f"wrote {out}", file=sys.stderr)


if __name__ == "__main__":
    main()

"""Turn results/*.json into results/SUMMARY.md (the tables the README quotes)."""

from __future__ import annotations

import json
from pathlib import Path

RESULTS = Path("results")


def load(name: str) -> dict | None:
    path = RESULTS / name
    return json.loads(path.read_text()) if path.exists() else None


def cooldown_section() -> list[str]:
    data = load("repro_40405.json")
    if not data:
        return []
    lines = [
        f"## #40405: single deployment + fallback, 503 outage (LiteLLM {data['litellm_version']})",
        "",
        "| Variant | Router settings | Primary model_info | Attempts on the dead primary, request by request | Average per request | Median latency (s) | Max latency (s) | Served after outage |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in data["results"]:
        by_request = r.get("primary_attempts_by_outage_request") or []
        average = round(sum(by_request) / len(by_request), 2) if by_request else r["primary_attempts_per_outage_request"]
        lines.append(
            f"| {r['variant']} | {fmt(r.get('router_settings'))} | {fmt(r.get('primary_model_info'))} | "
            f"{' '.join(str(n) for n in by_request)} | {average} | "
            f"{r['outage_latency_median_s']} | {r['outage_latency_max_s']} | {', '.join(r['served_by_after_outage'])} |"
        )
    return lines + [""]


def rules_section() -> list[str]:
    data = load("check_cooldown_rules.json")
    if not data:
        return []
    lines = [
        f"## When does a deployment cool down? (LiteLLM {data['litellm_version']}, defaults, num_retries=0)",
        "",
        "| Check | Requests | Attempts that reached the failing deployment | Cooled down after first failure? |",
        "| --- | --- | --- | --- |",
    ]
    for r in data["results"]:
        lines.append(f"| {r['check']} | {r['requests']} | {r['attempts_on_A']} | {'yes' if r['cooled_down_after_first_failure'] else 'no'} |")
    return lines + [""]


def fallback_section() -> list[str]:
    files = sorted(RESULTS.glob("repro_44815_litellm_*.json"))
    if not files:
        return []
    lines = [
        "## #44815: param rejected before sending, fallback configured",
        "",
        "| LiteLLM | Setting | Outcome | Served by | Calls to primary | Calls to backup |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for f in files:
        data = json.loads(f.read_text())
        for c in data["cases"]:
            lines.append(
                f"| {data['litellm_version']} | {fmt(c.get('settings'))} | {c['outcome']} | {c.get('served_by', '-')} | "
                f"{c.get('primary_calls', '-')} | {c.get('backup_calls', '-')} |"
            )
    return lines + [""]


def fmt(value: object) -> str:
    if isinstance(value, dict):
        return ", ".join(f"{k}={json.dumps(v) if isinstance(v, dict) else v}" for k, v in value.items())
    return str(value)


def main() -> None:
    lines = ["# Results", ""] + cooldown_section() + rules_section() + fallback_section()
    proxy = RESULTS / "proxy_demo.txt"
    if proxy.exists():
        lines += ["## Proxy demo (raw)", "", "```text", proxy.read_text().strip(), "```", ""]
    out = RESULTS / "SUMMARY.md"
    out.write_text("\n".join(lines))
    print(out.read_text())


if __name__ == "__main__":
    main()

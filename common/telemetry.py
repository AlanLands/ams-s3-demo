"""LLM call telemetry: one JSON line per `common.llm.complete()` call, appended by
`llm.py` itself so every scenario is covered without touching scenario code — S1
today, S2-S6 automatically once they call `complete()`.

Cost is deliberately NOT computed from invented pricing. `MODEL_PRICING_USD_PER_1M`
below is a placeholder (all zero) until real contracted/list rates are filled in;
until then every dashboard cost figure reads as unset rather than a fabricated
number presented as fact.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path

# (input_usd_per_1M_tokens, output_usd_per_1M_tokens) — fill in real rates before
# trusting any cost total this module reports.
MODEL_PRICING_USD_PER_1M: dict[str, tuple[float, float]] = {}


def _telemetry_path() -> Path:
    return Path(os.environ.get("LLM_TELEMETRY_PATH", ".cache/llm/telemetry.jsonl"))


def log_call(
    *,
    scenario: str,
    beat: str,
    provider: str,
    model: str,
    cached: bool,
    latency_s: float,
    input_tokens: int | None,
    output_tokens: int | None,
    success: bool,
    error: str | None = None,
) -> None:
    path = _telemetry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": _now_iso(),
        "scenario": scenario,
        "beat": beat,
        "provider": provider,
        "model": model,
        "cached": cached,
        "latency_s": round(latency_s, 3),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "success": success,
        "error": error,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def _now_iso() -> str:
    from datetime import datetime

    return datetime.now(UTC).isoformat()


def read_calls(path: Path | None = None) -> list[dict]:
    target = path or _telemetry_path()
    if not target.exists():
        return []
    calls = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            calls.append(json.loads(line))
    return calls


def scenario_of(cache_key: str | None) -> tuple[str, str]:
    """Split a `s1_quality_gate:INC000001`-shaped cache_key into (scenario, beat).

    Falls back to ("unknown", "unknown") for calls made without a cache_key or
    that don't follow the `<scenario>_<beat>:<id>` convention documented in each
    scenario's design doc.
    """
    if not cache_key:
        return "unknown", "unknown"
    prefix = cache_key.split(":", 1)[0]
    parts = prefix.split("_", 1)
    if len(parts) != 2:
        return "unknown", prefix
    return parts[0], parts[1]


def estimated_cost_usd(
    model: str, input_tokens: int | None, output_tokens: int | None
) -> float | None:
    rates = MODEL_PRICING_USD_PER_1M.get(model)
    if rates is None or input_tokens is None or output_tokens is None:
        return None
    input_rate, output_rate = rates
    return (input_tokens / 1_000_000) * input_rate + (output_tokens / 1_000_000) * output_rate


@dataclass(frozen=True)
class ScenarioSummary:
    scenario: str
    total_calls: int
    live_calls: int
    cached_calls: int
    input_tokens: int
    output_tokens: int
    avg_live_latency_s: float | None
    avg_cached_latency_s: float | None
    estimated_cost_usd: float | None


def summarize_by_scenario(calls: list[dict]) -> list[ScenarioSummary]:
    by_scenario: dict[str, list[dict]] = {}
    for call in calls:
        by_scenario.setdefault(call.get("scenario", "unknown"), []).append(call)

    summaries = []
    for scenario, rows in sorted(by_scenario.items()):
        live = [r for r in rows if not r["cached"]]
        cached = [r for r in rows if r["cached"]]
        input_tokens = sum(r.get("input_tokens") or 0 for r in live)
        output_tokens = sum(r.get("output_tokens") or 0 for r in live)
        costs = [
            estimated_cost_usd(r["model"], r.get("input_tokens"), r.get("output_tokens"))
            for r in live
        ]
        known_costs = [c for c in costs if c is not None]
        summaries.append(
            ScenarioSummary(
                scenario=scenario,
                total_calls=len(rows),
                live_calls=len(live),
                cached_calls=len(cached),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                avg_live_latency_s=(
                    sum(r["latency_s"] for r in live) / len(live) if live else None
                ),
                avg_cached_latency_s=(
                    sum(r["latency_s"] for r in cached) / len(cached) if cached else None
                ),
                estimated_cost_usd=sum(known_costs) if known_costs else None,
            )
        )
    return summaries


def cache_hit_rate(calls: list[dict]) -> float | None:
    if not calls:
        return None
    return sum(1 for c in calls if c["cached"]) / len(calls)

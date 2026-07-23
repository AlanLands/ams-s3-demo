from pathlib import Path

from common.telemetry import (
    cache_hit_rate,
    estimated_cost_usd,
    log_call,
    read_calls,
    scenario_of,
    summarize_by_scenario,
)


def test_scenario_of_parses_scenario_and_beat():
    assert scenario_of("s1_quality_gate:INC000001") == ("s1", "quality_gate")


def test_scenario_of_handles_missing_cache_key():
    assert scenario_of(None) == ("unknown", "unknown")


def test_scenario_of_handles_key_without_underscore():
    assert scenario_of("chatbot:abc") == ("unknown", "chatbot")


def test_log_call_and_read_calls_roundtrip(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LLM_TELEMETRY_PATH", str(tmp_path / "telemetry.jsonl"))
    log_call(
        scenario="s1",
        beat="triage",
        provider="anthropic",
        model="claude-sonnet-5",
        cached=False,
        latency_s=1.5,
        input_tokens=100,
        output_tokens=50,
        success=True,
    )
    log_call(
        scenario="s1",
        beat="triage",
        provider="anthropic",
        model="claude-sonnet-5",
        cached=True,
        latency_s=0.01,
        input_tokens=None,
        output_tokens=None,
        success=True,
    )
    calls = read_calls()
    assert len(calls) == 2
    assert calls[0]["scenario"] == "s1"
    assert calls[1]["cached"] is True


def test_read_calls_returns_empty_list_when_file_missing(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LLM_TELEMETRY_PATH", str(tmp_path / "does_not_exist.jsonl"))
    assert read_calls() == []


def test_cache_hit_rate():
    calls = [{"cached": True}, {"cached": True}, {"cached": False}, {"cached": False}]
    assert cache_hit_rate(calls) == 0.5


def test_cache_hit_rate_empty():
    assert cache_hit_rate([]) is None


def test_estimated_cost_usd_unset_by_default():
    assert estimated_cost_usd("claude-sonnet-5", 1000, 500) is None


def test_estimated_cost_usd_with_configured_rate(monkeypatch):
    import common.telemetry as telemetry

    monkeypatch.setitem(telemetry.MODEL_PRICING_USD_PER_1M, "test-model", (1.0, 2.0))
    cost = estimated_cost_usd("test-model", 1_000_000, 500_000)
    assert cost == 1.0 + 1.0  # 1M input @ $1/1M + 0.5M output @ $2/1M


def test_summarize_by_scenario_splits_live_and_cached():
    calls = [
        {
            "scenario": "s1",
            "beat": "triage",
            "provider": "anthropic",
            "model": "claude-sonnet-5",
            "cached": False,
            "latency_s": 2.0,
            "input_tokens": 200,
            "output_tokens": 100,
        },
        {
            "scenario": "s1",
            "beat": "triage",
            "provider": "anthropic",
            "model": "claude-sonnet-5",
            "cached": True,
            "latency_s": 0.05,
            "input_tokens": None,
            "output_tokens": None,
        },
    ]
    summaries = summarize_by_scenario(calls)
    assert len(summaries) == 1
    s = summaries[0]
    assert s.scenario == "s1"
    assert s.total_calls == 2
    assert s.live_calls == 1
    assert s.cached_calls == 1
    assert s.input_tokens == 200
    assert s.output_tokens == 100
    assert s.avg_live_latency_s == 2.0
    assert s.avg_cached_latency_s == 0.05

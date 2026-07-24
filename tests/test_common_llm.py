from pathlib import Path

import pytest

import common.llm as llm
from common.llm import LLMError, complete, parse_json_response, stream_complete
from common.telemetry import read_calls


def test_parses_plain_json():
    data = parse_json_response('{"a": 1, "b": 2}', required_keys={"a", "b"})
    assert data == {"a": 1, "b": 2}


def test_strips_markdown_code_fence():
    response = '```json\n{"a": 1}\n```'
    assert parse_json_response(response, required_keys={"a"}) == {"a": 1}


def test_strips_bare_code_fence_without_json_tag():
    response = "```\n{\"a\": 1}\n```"
    assert parse_json_response(response, required_keys={"a"}) == {"a": 1}


def test_raises_llm_error_not_json_decode_error_on_garbage():
    with pytest.raises(LLMError):
        parse_json_response("Sure! Here's my answer: not actually JSON.")


def test_raises_llm_error_on_missing_required_key():
    with pytest.raises(LLMError):
        parse_json_response('{"a": 1}', required_keys={"a", "b"})


def test_raises_llm_error_when_top_level_is_not_an_object():
    with pytest.raises(LLMError):
        parse_json_response("[1, 2, 3]")


def _isolate_llm_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("LLM_TELEMETRY_PATH", str(tmp_path / "telemetry.jsonl"))
    monkeypatch.chdir(tmp_path)


def test_complete_logs_telemetry_on_live_call(tmp_path: Path, monkeypatch):
    _isolate_llm_env(tmp_path, monkeypatch)
    monkeypatch.setitem(
        llm._PROVIDER_CALLERS, "anthropic", lambda prompt, system, json_mode: ("hello", 10, 5)
    )

    result = complete("hi", cache_key="s1_triage:INC000099")

    assert result == "hello"
    calls = read_calls()
    assert len(calls) == 1
    assert calls[0]["scenario"] == "s1"
    assert calls[0]["beat"] == "triage"
    assert calls[0]["cached"] is False
    assert calls[0]["input_tokens"] == 10
    assert calls[0]["output_tokens"] == 5
    assert calls[0]["success"] is True


def test_complete_logs_telemetry_on_cache_hit(tmp_path: Path, monkeypatch):
    _isolate_llm_env(tmp_path, monkeypatch)
    call_count = 0

    def fake_call(prompt, system, json_mode):
        nonlocal call_count
        call_count += 1
        return "hello", 10, 5

    monkeypatch.setitem(llm._PROVIDER_CALLERS, "anthropic", fake_call)

    complete("hi", cache_key="s1_triage:INC000099")
    complete("hi", cache_key="s1_triage:INC000099")

    assert call_count == 1  # second call hit cache, no live call made
    calls = read_calls()
    assert len(calls) == 2
    assert calls[0]["cached"] is False
    assert calls[1]["cached"] is True
    assert calls[1]["input_tokens"] is None


def test_complete_cache_hit_reports_real_usage_via_usage_out(tmp_path: Path, monkeypatch):
    """A cache HIT must still be able to answer 'what did this cost' for the
    UI's scoped-vs-naive token panel — the first (live) call's real,
    provider-reported usage is persisted alongside the response and replayed
    on every later hit, not just returned once and discarded."""
    _isolate_llm_env(tmp_path, monkeypatch)
    monkeypatch.setitem(
        llm._PROVIDER_CALLERS, "anthropic", lambda prompt, system, json_mode: ("hello", 3502, 210)
    )

    complete("a fairly long prompt", cache_key="s3_impact_analysis:coverage_upgrade:v2")

    usage_out: dict = {}
    result = complete(
        "a fairly long prompt",
        cache_key="s3_impact_analysis:coverage_upgrade:v2",
        usage_out=usage_out,
    )

    assert result == "hello"
    assert usage_out == {"input_tokens": 3502, "output_tokens": 210}
    assert "estimated" not in usage_out


def test_complete_cache_hit_estimates_usage_when_none_was_recorded(tmp_path: Path, monkeypatch):
    """An older cache entry written before usage capture existed only has
    `{"response": ...}` — no `usage`, but the prompt IS available (this repo
    has always stored it). A hit on such an entry should still degrade to an
    honest, clearly-flagged estimate rather than silently reporting nothing."""
    _isolate_llm_env(tmp_path, monkeypatch)
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True)
    path = cache_dir / "deadbeef.json"
    path.write_text(
        llm.json.dumps({"response": "a" * 40, "prompt": "b" * 400}), encoding="utf-8"
    )
    monkeypatch.setattr(llm, "_cache_path", lambda *a, **k: path)

    usage_out: dict = {}
    result = complete("ignored", usage_out=usage_out)

    assert result == "a" * 40
    assert usage_out == {"input_tokens": 100, "output_tokens": 10, "estimated": True}


def test_complete_cache_hit_leaves_usage_out_empty_with_no_prompt_or_usage(
    tmp_path: Path, monkeypatch
):
    """The oldest possible cache shape — bare `{"response": ...}`, no prompt
    either — has nothing to estimate from. Leaving usage_out untouched (the
    panel shows "unavailable") is more honest than fabricating a number."""
    _isolate_llm_env(tmp_path, monkeypatch)
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True)
    path = cache_dir / "deadbeef.json"
    path.write_text(llm.json.dumps({"response": "hello"}), encoding="utf-8")
    monkeypatch.setattr(llm, "_cache_path", lambda *a, **k: path)

    usage_out: dict = {}
    result = complete("ignored", usage_out=usage_out)

    assert result == "hello"
    assert usage_out == {}


def test_complete_logs_telemetry_on_failure(tmp_path: Path, monkeypatch):
    _isolate_llm_env(tmp_path, monkeypatch)

    def failing_call(prompt, system, json_mode):
        raise RuntimeError("provider down")

    monkeypatch.setitem(llm._PROVIDER_CALLERS, "anthropic", failing_call)

    with pytest.raises(LLMError):
        complete("hi", cache_key="s1_triage:INC000099", retries=0)

    calls = read_calls()
    assert len(calls) == 1
    assert calls[0]["success"] is False
    assert "provider down" in calls[0]["error"]


def test_stream_complete_live_yields_provider_chunks_and_logs(tmp_path: Path, monkeypatch):
    _isolate_llm_env(tmp_path, monkeypatch)
    monkeypatch.setenv("LLM_MODE", "live")

    def fake_stream(prompt, system, json_mode, *, usage_out=None):
        assert prompt == "hi"
        assert system == "sys"
        assert json_mode is False
        if usage_out is not None:
            usage_out["input_tokens"] = 3
            usage_out["output_tokens"] = 2
        yield "he"
        yield "llo"

    monkeypatch.setitem(llm._PROVIDER_STREAMERS, "anthropic", fake_stream)

    chunks = list(stream_complete("hi", system="sys", cache_key="s3_codegen"))

    assert chunks == ["he", "llo"]
    calls = read_calls()
    assert len(calls) == 1
    assert calls[0]["scenario"] == "s3"
    assert calls[0]["beat"] == "codegen"
    assert calls[0]["cached"] is False
    assert calls[0]["input_tokens"] == 3
    assert calls[0]["output_tokens"] == 2
    assert calls[0]["success"] is True


def test_stream_complete_record_writes_s3_replay_cache(tmp_path: Path, monkeypatch):
    _isolate_llm_env(tmp_path, monkeypatch)
    monkeypatch.setenv("LLM_MODE", "record")
    monkeypatch.setenv("ANTHROPIC_MODEL", "test-model")
    def fake_stream(prompt, system, json_mode, *, usage_out=None):
        if usage_out is not None:
            usage_out["input_tokens"] = 4
            usage_out["output_tokens"] = 2
        return iter(["a", "b"])

    monkeypatch.setitem(llm._PROVIDER_STREAMERS, "anthropic", fake_stream)

    assert list(stream_complete("prompt", system="system", cache_key="s3_codegen")) == ["a", "b"]

    cache_file = tmp_path / "s3_enhancement" / "cache" / "s3_codegen.json"
    data = llm.json.loads(cache_file.read_text(encoding="utf-8"))
    assert data["prompt"] == "prompt"
    assert data["system"] == "system"
    assert data["provider"] == "anthropic"
    assert data["model"] == "test-model"
    assert data["response"] == "ab"


def test_stream_complete_replay_applies_substitutions(tmp_path: Path, monkeypatch):
    _isolate_llm_env(tmp_path, monkeypatch)
    monkeypatch.setenv("LLM_MODE", "replay")
    cache_dir = tmp_path / "s3_enhancement" / "cache"
    cache_dir.mkdir(parents=True)
    (cache_dir / "s3_codegen.json").write_text(
        llm.json.dumps(
            {
                "prompt": "prompt",
                "system": None,
                "provider": "openai",
                "model": "gpt-test",
                "response": "tier={{TIER_NAME}}",
            }
        ),
        encoding="utf-8",
    )

    chunks = list(
        stream_complete(
            "ignored",
            cache_key="s3_codegen",
            replay_substitutions={"{{TIER_NAME}}": "Platinum"},
            chunk_delay=-1,
        )
    )

    assert "".join(chunks) == "tier=Platinum"
    calls = read_calls()
    assert calls[0]["cached"] is True
    assert calls[0]["provider"] == "openai"


def test_stream_complete_replay_missing_cache_falls_back_to_live_and_records(
    tmp_path: Path, monkeypatch
):
    _isolate_llm_env(tmp_path, monkeypatch)
    monkeypatch.setenv("LLM_MODE", "replay")

    def fake_stream(prompt, system, json_mode, *, usage_out=None):
        if usage_out is not None:
            usage_out["input_tokens"] = 1
            usage_out["output_tokens"] = 1
        return iter(["live", "-fallback"])

    monkeypatch.setitem(llm._PROVIDER_STREAMERS, "anthropic", fake_stream)

    chunks = list(stream_complete("ignored", cache_key="s3_missing", chunk_delay=-1))

    assert "".join(chunks) == "live-fallback"
    cache_file = tmp_path / "s3_enhancement" / "cache" / "s3_missing.json"
    assert cache_file.exists()  # replay-primary: a cold cache still leaves a recording behind


def test_llm_mode_defaults_to_replay_when_unset(monkeypatch):
    monkeypatch.delenv("LLM_MODE", raising=False)
    assert llm._llm_mode() == "replay"


def test_resolve_provider_raises_without_key_mentions_ollama(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(LLMError, match="ollama"):
        llm._resolve_provider()


def test_call_anthropic_wraps_system_prompt_with_cache_control(monkeypatch):
    import anthropic

    captured = {}

    class FakeUsage:
        input_tokens = 11
        output_tokens = 4

    class FakeContent:
        text = "hi there"

    class FakeResponse:
        content = [FakeContent()]
        usage = FakeUsage()

    class FakeMessages:
        def create(self, **kwargs):
            captured.update(kwargs)
            return FakeResponse()

    class FakeClient:
        def __init__(self, api_key=None):
            pass

        messages = FakeMessages()

    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)

    text, input_tokens, output_tokens = llm._call_anthropic("hi", "be nice", False)

    assert text == "hi there"
    assert input_tokens == 11
    assert output_tokens == 4
    # A static system prompt reused across every call to this beat is exactly
    # what Anthropic's cache_control is for — the plain string must never be
    # sent bare once this is in place.
    assert captured["system"] == [
        {"type": "text", "text": "be nice", "cache_control": {"type": "ephemeral"}}
    ]


def test_call_anthropic_without_system_sends_no_system_kwarg(monkeypatch):
    import anthropic

    captured = {}

    class FakeUsage:
        input_tokens = 1
        output_tokens = 1

    class FakeContent:
        text = "ok"

    class FakeResponse:
        content = [FakeContent()]
        usage = FakeUsage()

    class FakeMessages:
        def create(self, **kwargs):
            captured.update(kwargs)
            return FakeResponse()

    class FakeClient:
        def __init__(self, api_key=None):
            pass

        messages = FakeMessages()

    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)

    llm._call_anthropic("hi", None, False)

    assert "system" not in captured


def test_stream_anthropic_wraps_system_prompt_with_cache_control(monkeypatch):
    import anthropic

    captured = {}

    class FakeFinalUsage:
        input_tokens = 9
        output_tokens = 6

    class FakeFinalMessage:
        usage = FakeFinalUsage()

    class FakeStreamCtx:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.text_stream = iter(["he", "llo"])

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get_final_message(self):
            return FakeFinalMessage()

    class FakeMessages:
        def stream(self, **kwargs):
            return FakeStreamCtx(**kwargs)

    class FakeClient:
        def __init__(self, api_key=None):
            pass

        messages = FakeMessages()

    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)

    usage_out: dict = {}
    chunks = list(llm._stream_anthropic("hi", "be nice", False, usage_out=usage_out))

    assert chunks == ["he", "llo"]
    assert usage_out == {"input_tokens": 9, "output_tokens": 6}
    assert captured["system"] == [
        {"type": "text", "text": "be nice", "cache_control": {"type": "ephemeral"}}
    ]


def test_call_ollama_uses_openai_compatible_endpoint(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.1")
    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)

            class Usage:
                prompt_tokens = 7
                completion_tokens = 3

            class Message:
                content = "ok"

            class Choice:
                message = Message()

            class Response:
                choices = [Choice()]
                usage = Usage()

            return Response()

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    monkeypatch.setattr(llm, "_ollama_client", lambda: FakeClient())

    text, input_tokens, output_tokens = llm._call_ollama("hi", None, False)

    assert text == "ok"
    assert input_tokens == 7
    assert output_tokens == 3
    assert captured["model"] == "llama3.1"

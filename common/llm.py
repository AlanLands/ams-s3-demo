"""Provider-agnostic LLM access. Every LLM call in this repo goes through `complete()`.

Provider selection:
- `LLM_PROVIDER` env var wins if set ("anthropic", "openai", or "ollama").
- Otherwise auto-detect from which API key is present; if both are present, prefer
  OpenAI (leadership steer — the end client is planning OpenAI). Ollama is never
  auto-detected (it has no API key to detect) — set `LLM_PROVIDER=ollama`
  explicitly to run against a local model (`OLLAMA_BASE_URL`/`OLLAMA_MODEL`).

No provider-specific object, response shape, or parameter is allowed to leak past
this module — callers only ever see `str` in, `str` out.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Iterator
from pathlib import Path

from dotenv import load_dotenv

from common.telemetry import log_call, scenario_of

load_dotenv()


class LLMError(Exception):
    """Raised for any provider failure, auth issue, or misconfiguration."""


def _cache_dir() -> Path:
    return Path(os.environ.get("LLM_CACHE_DIR", ".cache/llm"))


def _llm_mode() -> str:
    # Default is replay — the demo-reliability rule (CLAUDE.md): recorded outputs
    # are primary, live calls are the fallback/opt-in, never the reverse.
    mode = os.environ.get("LLM_MODE", "replay").lower()
    if mode not in {"live", "record", "replay"}:
        raise LLMError(f"Unknown LLM_MODE {mode!r}; expected 'live', 'record', or 'replay'")
    return mode


def _stream_cache_path(cache_key: str) -> Path:
    return Path("s3_enhancement") / "cache" / f"{cache_key}.json"


def _cache_enabled() -> bool:
    return os.environ.get("LLM_NO_CACHE", "0") != "1"


def _resolve_provider() -> str:
    explicit = os.environ.get("LLM_PROVIDER")
    if explicit:
        return explicit.lower()

    has_openai = bool(os.environ.get("OPENAI_API_KEY"))
    has_anthropic = bool(os.environ.get("ANTHROPIC_API_KEY"))
    if has_openai:
        return "openai"
    if has_anthropic:
        return "anthropic"
    raise LLMError(
        "No LLM provider configured: set LLM_PROVIDER ('openai', 'anthropic', or "
        "'ollama') and, for the hosted providers, the matching API key in .env"
    )


def _cache_path(
    provider: str, model: str, system: str | None, prompt: str, cache_key: str | None
) -> Path:
    key_material = cache_key or f"{provider}|{model}|{system or ''}|{prompt}"
    digest = hashlib.sha256(key_material.encode("utf-8")).hexdigest()
    return _cache_dir() / f"{digest}.json"


def _read_cache(path: Path) -> str | None:
    if not _cache_enabled() or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))["response"]


def _write_cache(path: Path, response: str) -> None:
    if not _cache_enabled():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"response": response}), encoding="utf-8")


def _call_anthropic(prompt: str, system: str | None, json_mode: bool) -> tuple[str, int, int]:
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
    kwargs: dict = {}
    if system:
        kwargs["system"] = system
    if json_mode:
        prompt = prompt + "\n\nRespond with valid JSON only, no surrounding prose."

    response = client.messages.create(
        model=model,
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
        **kwargs,
    )
    return response.content[0].text, response.usage.input_tokens, response.usage.output_tokens


def _call_openai(prompt: str, system: str | None, json_mode: bool) -> tuple[str, int, int]:
    from openai import OpenAI

    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    model = os.environ.get("OPENAI_MODEL", "gpt-5")
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    kwargs: dict = {}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    response = client.chat.completions.create(model=model, messages=messages, **kwargs)
    usage = response.usage
    return (
        response.choices[0].message.content,
        usage.prompt_tokens if usage else 0,
        usage.completion_tokens if usage else 0,
    )


def _ollama_client():
    from openai import OpenAI

    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    # Ollama exposes an OpenAI-compatible endpoint at /v1; reusing the pinned
    # openai client keeps this dependency-free (locked-down-environment rule).
    # The api_key value is required by the client but ignored by Ollama.
    return OpenAI(base_url=f"{base_url}/v1", api_key="ollama")


def _call_ollama(prompt: str, system: str | None, json_mode: bool) -> tuple[str, int, int]:
    client = _ollama_client()
    model = os.environ.get("OLLAMA_MODEL", "llama3.1")
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    kwargs: dict = {}
    if json_mode:
        # Both belt and suspenders for local models: format enforcement plus the
        # explicit instruction (some models loop or emit prose without it).
        kwargs["response_format"] = {"type": "json_object"}
        prompt = prompt + "\n\nRespond with valid JSON only, no surrounding prose."
    messages.append({"role": "user", "content": prompt})

    response = client.chat.completions.create(model=model, messages=messages, **kwargs)
    usage = response.usage
    return (
        response.choices[0].message.content or "",
        usage.prompt_tokens if usage else 0,
        usage.completion_tokens if usage else 0,
    )


def _stream_ollama(
    prompt: str,
    system: str | None,
    json_mode: bool,
    *,
    usage_out: dict | None = None,
) -> Iterator[str]:
    client = _ollama_client()
    model = os.environ.get("OLLAMA_MODEL", "llama3.1")
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    kwargs: dict = {}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
        prompt = prompt + "\n\nRespond with valid JSON only, no surrounding prose."
    messages.append({"role": "user", "content": prompt})

    stream = client.chat.completions.create(model=model, messages=messages, stream=True, **kwargs)
    for event in stream:
        delta = event.choices[0].delta.content if event.choices else None
        # No stream_options={"include_usage": True} here: older Ollama builds
        # don't send usage chunks. When one does, capture it; otherwise
        # stream_complete's telemetry falls back to length estimates.
        usage = getattr(event, "usage", None)
        if usage_out is not None and usage is not None:
            usage_out["input_tokens"] = usage.prompt_tokens
            usage_out["output_tokens"] = usage.completion_tokens
        if delta:
            yield delta


def _stream_anthropic(
    prompt: str,
    system: str | None,
    json_mode: bool,
    *,
    usage_out: dict | None = None,
) -> Iterator[str]:
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
    kwargs: dict = {}
    if system:
        kwargs["system"] = system
    if json_mode:
        prompt = prompt + "\n\nRespond with valid JSON only, no surrounding prose."

    with client.messages.stream(
        model=model,
        max_tokens=12000,
        messages=[{"role": "user", "content": prompt}],
        **kwargs,
    ) as stream:
        for text in stream.text_stream:
            if text:
                yield text
        if usage_out is not None:
            final = stream.get_final_message()
            usage_out["input_tokens"] = final.usage.input_tokens
            usage_out["output_tokens"] = final.usage.output_tokens


def _stream_openai(
    prompt: str,
    system: str | None,
    json_mode: bool,
    *,
    usage_out: dict | None = None,
) -> Iterator[str]:
    from openai import OpenAI

    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    model = os.environ.get("OPENAI_MODEL", "gpt-5")
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    kwargs: dict = {}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    stream = client.chat.completions.create(
        model=model,
        messages=messages,
        stream=True,
        stream_options={"include_usage": True},
        max_completion_tokens=12000,
        **kwargs,
    )
    for event in stream:
        delta = event.choices[0].delta.content if event.choices else None
        if usage_out is not None and getattr(event, "usage", None) is not None:
            usage_out["input_tokens"] = event.usage.prompt_tokens
            usage_out["output_tokens"] = event.usage.completion_tokens
        if delta:
            yield delta


_PROVIDER_CALLERS = {
    "anthropic": _call_anthropic,
    "openai": _call_openai,
    "ollama": _call_ollama,
}

_PROVIDER_STREAMERS = {
    "anthropic": _stream_anthropic,
    "openai": _stream_openai,
    "ollama": _stream_ollama,
}


def complete(
    prompt: str,
    *,
    system: str | None = None,
    json_mode: bool = False,
    cache_key: str | None = None,
    retries: int = 2,
    usage_out: dict | None = None,
) -> str:
    """Send a prompt to the configured provider and return its text response.

    `cache_key` pins a specific cache entry (used for must-land demo beats so the
    exact same response is served every rehearsal); omit it to cache by content hash.
    """
    provider = _resolve_provider()
    if provider not in _PROVIDER_CALLERS:
        raise LLMError(
            f"Unknown LLM_PROVIDER {provider!r}; expected 'anthropic', 'openai', or 'ollama'"
        )

    model = _model_for(provider)
    scenario, beat = scenario_of(cache_key)
    path = _cache_path(provider, model, system, prompt, cache_key)

    t0 = time.monotonic()
    cached = _read_cache(path)
    if cached is not None:
        log_call(
            scenario=scenario,
            beat=beat,
            provider=provider,
            model=model,
            cached=True,
            latency_s=time.monotonic() - t0,
            input_tokens=None,
            output_tokens=None,
            success=True,
        )
        return cached

    caller = _PROVIDER_CALLERS[provider]
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            result, input_tokens, output_tokens = caller(prompt, system, json_mode)
            _write_cache(path, result)
            log_call(
                scenario=scenario,
                beat=beat,
                provider=provider,
                model=model,
                cached=False,
                latency_s=time.monotonic() - t0,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                success=True,
            )
            if usage_out is not None:
                usage_out["input_tokens"] = input_tokens
                usage_out["output_tokens"] = output_tokens
            return result
        except Exception as exc:  # noqa: BLE001 — collapsed into one wrapper exception type
            last_error = exc
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    log_call(
        scenario=scenario,
        beat=beat,
        provider=provider,
        model=model,
        cached=False,
        latency_s=time.monotonic() - t0,
        input_tokens=None,
        output_tokens=None,
        success=False,
        error=str(last_error),
    )
    raise LLMError(
        f"{provider} call failed after {retries + 1} attempts: {last_error}"
    ) from last_error


def stream_complete(
    prompt: str,
    *,
    system: str | None = None,
    json_mode: bool = False,
    cache_key: str,
    retries: int = 2,
    replay_substitutions: dict[str, str] | None = None,
    chunk_delay: float = 0.0,
    usage_out: dict | None = None,
) -> Iterator[str]:
    """Stream a provider response, or replay a recorded S3 response by cache key.

    This is intentionally independent from `complete()`: S3 code generation uses
    a human-readable replay store, while existing S1/S2/S6 calls keep using the
    hash-keyed `.cache/llm` cache behind `complete()`.
    """
    mode = _llm_mode()
    scenario, beat = scenario_of(cache_key)
    t0 = time.monotonic()

    if mode == "replay":
        if _stream_cache_path(cache_key).exists():
            yield from _stream_replay(
                cache_key=cache_key,
                scenario=scenario,
                beat=beat,
                replay_substitutions=replay_substitutions,
                chunk_delay=chunk_delay,
                started_at=t0,
            )
            return
        # Replay-primary with live fallback (CLAUDE.md demo-reliability rule):
        # a missing recording degrades to a live call that also records, so
        # the next run replays. The old behavior — raising on a missing
        # recording — turned a cold cache into a dead demo beat.
        mode = "record"

    provider = _resolve_provider()
    if provider not in _PROVIDER_STREAMERS:
        raise LLMError(
            f"Unknown LLM_PROVIDER {provider!r}; expected 'anthropic', 'openai', or 'ollama'"
        )

    model = _model_for(provider)
    streamer = _PROVIDER_STREAMERS[provider]
    chunks: list[str] = []
    last_error: Exception | None = None
    usage: dict = {}
    for attempt in range(retries + 1):
        try:
            for chunk in streamer(prompt, system, json_mode, usage_out=usage):
                chunks.append(chunk)
                yield chunk
            response = "".join(chunks)
            if usage_out is not None:
                usage_out.update(usage)
            if mode == "record":
                _write_stream_cache(
                    cache_key=cache_key,
                    prompt=prompt,
                    system=system,
                    provider=provider,
                    model=model,
                    response=response,
                )
            log_call(
                scenario=scenario,
                beat=beat,
                provider=provider,
                model=model,
                cached=False,
                latency_s=time.monotonic() - t0,
                input_tokens=usage.get("input_tokens", len(prompt)),
                output_tokens=usage.get("output_tokens", len(response)),
                success=True,
            )
            return
        except Exception as exc:  # noqa: BLE001 — provider details collapse to LLMError
            chunks.clear()
            usage.clear()
            last_error = exc
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    log_call(
        scenario=scenario,
        beat=beat,
        provider=provider,
        model=model,
        cached=False,
        latency_s=time.monotonic() - t0,
        input_tokens=None,
        output_tokens=None,
        success=False,
        error=str(last_error),
    )
    raise LLMError(
        f"{provider} stream failed after {retries + 1} attempts: {last_error}"
    ) from last_error


def _stream_replay(
    *,
    cache_key: str,
    scenario: str,
    beat: str,
    replay_substitutions: dict[str, str] | None,
    chunk_delay: float,
    started_at: float,
) -> Iterator[str]:
    path = _stream_cache_path(cache_key)
    if not path.exists():
        raise LLMError(f"No replay cache exists for {cache_key!r} at {path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        response = str(data["response"])
    except (KeyError, json.JSONDecodeError) as exc:
        raise LLMError(f"Replay cache {path} is malformed") from exc

    for old, new in (replay_substitutions or {}).items():
        response = response.replace(old, new)

    delay = 0.02 if chunk_delay == 0.0 else chunk_delay
    for idx in range(0, len(response), 40):
        if delay > 0:
            time.sleep(delay)
        yield response[idx : idx + 40]

    provider = str(data.get("provider", "replay"))
    model = str(data.get("model", "replay"))
    log_call(
        scenario=scenario,
        beat=beat,
        provider=provider,
        model=model,
        cached=True,
        latency_s=time.monotonic() - started_at,
        input_tokens=None,
        output_tokens=len(response),
        success=True,
    )


def _write_stream_cache(
    *,
    cache_key: str,
    prompt: str,
    system: str | None,
    provider: str,
    model: str,
    response: str,
) -> None:
    path = _stream_cache_path(cache_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "prompt": prompt,
                "system": system,
                "provider": provider,
                "model": model,
                "response": response,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def parse_json_response(response: str, required_keys: set[str] = frozenset()) -> dict:
    """Parse a model JSON response into a dict, raising `LLMError` — not a raw
    `json.JSONDecodeError`/`KeyError` — on anything that doesn't match the expected
    shape. Every UI caller already handles `LLMError`; a stray markdown code fence or
    a missing field from a live model must degrade the same way a provider outage
    does, not crash past that one guard.
    """
    text = response.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError(f"model response was not valid JSON: {response[:200]!r}") from exc

    if not isinstance(data, dict):
        raise LLMError(f"model response was valid JSON but not an object: {response[:200]!r}")

    missing = required_keys - data.keys()
    if missing:
        raise LLMError(
            f"model response missing required keys {sorted(missing)}: {response[:200]!r}"
        )

    return data


def _model_for(provider: str) -> str:
    if provider == "anthropic":
        return os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
    if provider == "ollama":
        return os.environ.get("OLLAMA_MODEL", "llama3.1")
    return os.environ.get("OPENAI_MODEL", "gpt-5")

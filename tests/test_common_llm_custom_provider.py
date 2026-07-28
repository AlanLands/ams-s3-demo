"""The `custom` provider: any OpenAI-compatible endpoint the hosting team runs.

The happy paths run against a real HTTP server on localhost rather than a
mocked client. That is deliberate — the whole point of this provider is that
it talks to *someone else's* URL, so the thing worth proving is that a base
URL is honoured on the wire, not that a mock was called.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from common import llm
from common.llm import LLMError

pytestmark = pytest.mark.usefixtures("no_llm_cache")


@pytest.fixture
def no_llm_cache(monkeypatch, tmp_path):
    """Never read or write the repo's real .cache/llm during these tests."""
    monkeypatch.setenv("LLM_NO_CACHE", "1")
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path / "llmcache"))
    monkeypatch.setenv("LLM_MODE", "live")


class _Handler(BaseHTTPRequestHandler):
    """Minimal OpenAI-compatible chat-completions stub."""

    received: list[dict] = []

    def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler API
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        type(self).received.append({"path": self.path, "body": body,
                                    "auth": self.headers.get("Authorization")})
        payload = {
            "id": "chatcmpl-1",
            "object": "chat.completion",
            "choices": [
                {"index": 0, "message": {"role": "assistant", "content": "hello from custom"},
                 "finish_reason": "stop"}
            ],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
        }
        raw = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *_args):  # silence the test log
        pass


@pytest.fixture
def stub_endpoint():
    _Handler.received = []
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/v1", _Handler
    server.shutdown()
    server.server_close()


# --- configuration errors -----------------------------------------------


def test_missing_base_url_names_the_variable(monkeypatch):
    """A team wiring this into their sandbox should get one line to fix."""
    monkeypatch.setenv("LLM_PROVIDER", "custom")
    monkeypatch.delenv("CUSTOM_LLM_BASE_URL", raising=False)
    monkeypatch.setenv("CUSTOM_LLM_MODEL", "some-model")

    with pytest.raises(LLMError, match="CUSTOM_LLM_BASE_URL"):
        llm.complete("hi", retries=0)


def test_missing_model_names_the_variable(monkeypatch, stub_endpoint):
    base_url, _ = stub_endpoint
    monkeypatch.setenv("LLM_PROVIDER", "custom")
    monkeypatch.setenv("CUSTOM_LLM_BASE_URL", base_url)
    monkeypatch.delenv("CUSTOM_LLM_MODEL", raising=False)

    with pytest.raises(LLMError, match="CUSTOM_LLM_MODEL"):
        llm.complete("hi", retries=0)


def test_custom_is_never_auto_detected(monkeypatch):
    """Selecting this provider must be an explicit act — it has no key to
    sniff, and silently defaulting to someone's internal URL would be wrong."""
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("CUSTOM_LLM_BASE_URL", "http://should-not-be-used/v1")

    assert llm._resolve_provider() == "openai"


# --- the wire -----------------------------------------------------------


def test_complete_calls_the_configured_base_url(monkeypatch, stub_endpoint):
    base_url, handler = stub_endpoint
    monkeypatch.setenv("LLM_PROVIDER", "custom")
    monkeypatch.setenv("CUSTOM_LLM_BASE_URL", base_url)
    monkeypatch.setenv("CUSTOM_LLM_MODEL", "llama-3.3-70b")
    monkeypatch.setenv("CUSTOM_LLM_API_KEY", "sekret")

    answer = llm.complete("ping", system="be terse", retries=0)

    assert answer == "hello from custom"
    assert len(handler.received) == 1
    call = handler.received[0]
    assert call["path"].endswith("/chat/completions")
    assert call["body"]["model"] == "llama-3.3-70b"
    assert call["body"]["messages"][0] == {"role": "system", "content": "be terse"}
    assert call["auth"] == "Bearer sekret"


def test_api_key_is_optional_for_gateways_that_ignore_auth(monkeypatch, stub_endpoint):
    """Plenty of self-hosted gateways do no auth at all; an unset key must not
    be a hard failure."""
    base_url, handler = stub_endpoint
    monkeypatch.setenv("LLM_PROVIDER", "custom")
    monkeypatch.setenv("CUSTOM_LLM_BASE_URL", base_url)
    monkeypatch.setenv("CUSTOM_LLM_MODEL", "llama-3.3-70b")
    monkeypatch.delenv("CUSTOM_LLM_API_KEY", raising=False)

    assert llm.complete("ping", retries=0) == "hello from custom"
    assert handler.received[0]["auth"] == "Bearer not-required"


def test_trailing_slash_in_base_url_is_tolerated(monkeypatch, stub_endpoint):
    base_url, handler = stub_endpoint
    monkeypatch.setenv("LLM_PROVIDER", "custom")
    monkeypatch.setenv("CUSTOM_LLM_BASE_URL", base_url + "/")
    monkeypatch.setenv("CUSTOM_LLM_MODEL", "m")

    assert llm.complete("ping", retries=0) == "hello from custom"
    assert "//chat" not in handler.received[0]["path"]


def test_json_mode_asks_for_json_both_ways(monkeypatch, stub_endpoint):
    """Self-hosted models wrap JSON in prose more often than the hosted
    vendors, and not every gateway honours response_format — so the instruction
    goes in the prompt as well."""
    base_url, handler = stub_endpoint
    monkeypatch.setenv("LLM_PROVIDER", "custom")
    monkeypatch.setenv("CUSTOM_LLM_BASE_URL", base_url)
    monkeypatch.setenv("CUSTOM_LLM_MODEL", "m")

    llm.complete("give me data", json_mode=True, retries=0)

    body = handler.received[0]["body"]
    assert body["response_format"] == {"type": "json_object"}
    assert "valid JSON only" in body["messages"][-1]["content"]


def test_usage_is_reported_back(monkeypatch, stub_endpoint):
    base_url, _ = stub_endpoint
    monkeypatch.setenv("LLM_PROVIDER", "custom")
    monkeypatch.setenv("CUSTOM_LLM_BASE_URL", base_url)
    monkeypatch.setenv("CUSTOM_LLM_MODEL", "m")

    usage: dict = {}
    llm.complete("ping", retries=0, usage_out=usage)

    assert usage["input_tokens"] == 11
    assert usage["output_tokens"] == 7


def test_a_cached_narrative_call_never_touches_the_endpoint(
    monkeypatch, stub_endpoint, tmp_path
):
    """A warmed cache entry is served without any network call — this is what
    makes the demo survive a sandbox whose model is slow or unreachable."""
    base_url, handler = stub_endpoint
    monkeypatch.setenv("LLM_PROVIDER", "custom")
    monkeypatch.setenv("CUSTOM_LLM_BASE_URL", base_url)
    monkeypatch.setenv("CUSTOM_LLM_MODEL", "m")
    monkeypatch.setenv("LLM_NO_CACHE", "0")
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path / "c"))

    first = llm.complete("ping", cache_key="demo_beat", retries=0)
    assert len(handler.received) == 1

    second = llm.complete("ping", cache_key="demo_beat", retries=0)

    assert second == first
    assert len(handler.received) == 1, "second call should have been served from cache"


def test_complete_goes_live_on_a_cache_miss_even_in_replay_mode(
    monkeypatch, stub_endpoint, tmp_path
):
    """Documents a sharp edge, rather than asserting a guarantee that does not
    exist: `LLM_MODE=replay` is enforced by `stream_complete` (codegen/testgen),
    but `complete()` — every narrative beat — only consults its cache, and on a
    miss calls the provider regardless of mode.

    For a team pointing this at their own endpoint that means an un-warmed
    narrative beat WILL hit their gateway during a demo. Run
    `demo/warm_s3_cache.sh` first; see the demo steps doc.
    """
    base_url, handler = stub_endpoint
    monkeypatch.setenv("LLM_PROVIDER", "custom")
    monkeypatch.setenv("CUSTOM_LLM_BASE_URL", base_url)
    monkeypatch.setenv("CUSTOM_LLM_MODEL", "m")
    monkeypatch.setenv("LLM_MODE", "replay")
    monkeypatch.setenv("LLM_NO_CACHE", "0")
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path / "c"))

    assert llm.complete("ping", retries=0) == "hello from custom"
    assert len(handler.received) == 1

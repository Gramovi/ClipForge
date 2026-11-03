from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.config import Settings
from app.llm import LLMConfigError, LLMError, LLMProvider, LLMResult, LLMTransientError, get_provider
from app.llm.jsonfix import JSONRepairError, parse_json_loose
from app.llm.ollama_provider import OllamaProvider
from app.llm.pricing import cost, estimate_hour
from app.pipeline.finder import find_moments, parse_clips
from app.pipeline.moments import Window
from tests.conftest import make_words

CLIP = {
    "start": 1.0, "end": 20.0, "title": "Peníze nejsou všechno", "hook": "Hook", "reason": "Protože",
    "scores": {"hook": 80, "flow": 70, "value": 90, "trend": 60}, "virality_score": 82,
    "description": "Popisek", "hashtags": ["#penize", "investice"], "keywords": ["peníze"],
    "emojis": [{"word": "peníze", "emoji": "💰"}],
}


# ---- JSON repair ---------------------------------------------------------------------------

def test_parse_plain_and_fenced() -> None:
    assert parse_json_loose('{"a": 1}') == {"a": 1}
    assert parse_json_loose('Here you go:\n```json\n{"a": [1, 2]}\n```\nThanks') == {"a": [1, 2]}


def test_parse_trailing_commas_and_smart_quotes() -> None:
    assert parse_json_loose('{"a": [1, 2,],}') == {"a": [1, 2]}
    assert parse_json_loose('{“a”: “ěščř”}') == {"a": "ěščř"}


def test_parse_truncated_output_keeps_complete_items() -> None:
    text = '{"clips": [{"start": 1, "end": 2, "title": "A"}, {"start": 3, "end": 4, "title": "B"}, {"start": 5, "en'
    data = parse_json_loose(text)
    assert [c["title"] for c in data["clips"]] == ["A", "B"]


def test_parse_python_literal() -> None:
    assert parse_json_loose("{'ok': True, 'n': None}") == {"ok": True, "n": None}


def test_parse_raw_newlines_in_strings() -> None:
    assert parse_json_loose('{"t": "line1\nline2"}') == {"t": "line1\nline2"}


def test_parse_garbage_raises() -> None:
    with pytest.raises(JSONRepairError):
        parse_json_loose("no json here")
    with pytest.raises(JSONRepairError):
        parse_json_loose("")


def test_parse_clips_validation_and_relative_times() -> None:
    w = Window(0, 0, 10, 600.0, 1300.0)
    # relative times (0-based in the window) are shifted into the window
    clips = parse_clips(json.dumps({"clips": [CLIP]}), w)
    assert clips[0].start == 601.0
    assert clips[0].hashtags == ["#penize", "#investice"]
    # alternative top-level key + one invalid item
    clips = parse_clips(json.dumps({"moments": [{**CLIP, "start": 700, "end": 720}, {"foo": 1}]}), w)
    assert len(clips) == 1
    with pytest.raises(JSONRepairError):
        parse_clips(json.dumps({"clips": [{"foo": 1}]}), w)


# ---- provider switching -----------------------------------------------------------------------

def test_provider_switching() -> None:
    from app.llm.anthropic_provider import AnthropicProvider

    with pytest.raises(LLMConfigError) as e:
        get_provider(Settings(llm_provider="anthropic", anthropic_api_key=""))
    assert "ANTHROPIC_API_KEY" in str(e.value)
    p = get_provider(Settings(llm_provider="anthropic", anthropic_api_key="sk-test", anthropic_model="claude-haiku-5-5"))
    assert isinstance(p, AnthropicProvider) and p.model == "claude-haiku-5-5"
    p2 = get_provider(Settings(llm_provider="ollama", ollama_model="qwen2.5:7b"))
    assert isinstance(p2, OllamaProvider) and p2.is_local and p2.model == "qwen2.5:7b"


def _sse(events: list[tuple[str, dict[str, Any]]]) -> bytes:
    return "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events).encode()


def _anthropic_with(handler: Any) -> Any:
    import anthropic
    import httpx2  # the Anthropic SDK 2.x transport

    from app.llm.anthropic_provider import AnthropicProvider

    p = AnthropicProvider("sk-test", "claude-sonnet-5-5")
    p.client = anthropic.Anthropic(api_key="sk-test", max_retries=0, http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))
    return p


def test_anthropic_success_streaming() -> None:
    text = json.dumps({"clips": [CLIP]})
    seen: dict[str, Any] = {}

    def handler(req: Any) -> Any:
        import httpx2

        seen["body"] = json.loads(req.content)
        body = _sse([
            ("message_start", {"type": "message_start", "message": {
                "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-sonnet-5-5", "content": [],
                "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 1200, "output_tokens": 1}}}),
            ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
            ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}}),
            ("content_block_stop", {"type": "content_block_stop", "index": 0}),
            ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                               "usage": {"output_tokens": 345}}),
            ("message_stop", {"type": "message_stop"}),
        ])
        return httpx2.Response(200, content=body, headers={"content-type": "text/event-stream"})

    p = _anthropic_with(handler)
    res = p.complete_json("sys", "user", {"type": "object"})
    assert json.loads(res.text)["clips"][0]["title"] == "Peníze nejsou všechno"
    assert res.input_tokens == 1200 and res.output_tokens == 345
    assert seen["body"]["output_config"]["format"]["type"] == "json_schema"
    assert seen["body"]["model"] == "claude-sonnet-5-5"


@pytest.mark.parametrize(("code", "exc"), [(401, LLMConfigError), (404, LLMConfigError), (429, LLMTransientError),
                                           (529, LLMTransientError), (500, LLMTransientError), (400, LLMError)])
def test_anthropic_error_mapping(code: int, exc: type[Exception]) -> None:
    def handler(req: Any) -> Any:
        import httpx2

        return httpx2.Response(code, json={"type": "error", "error": {"type": "x", "message": "boom"}})

    p = _anthropic_with(handler)
    with pytest.raises(exc) as e:
        p.complete_json("s", "u", {})
    if code == 401:
        assert "neplatný" in str(e.value)


def test_ollama_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    def fake_post(url: str, json: dict[str, Any], timeout: Any) -> httpx.Response:
        calls.append(json)
        return httpx.Response(200, json={"message": {"content": '{"clips": []}'}, "prompt_eval_count": 10, "eval_count": 5},
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)
    p = OllamaProvider("http://ollama:11434", "qwen2.5:7b")
    res = p.complete_json("s", "u", {"type": "object"})
    assert res.text == '{"clips": []}' and res.input_tokens == 10
    assert calls[0]["format"] == {"type": "object"} and calls[0]["stream"] is False


def test_ollama_down(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(*a: Any, **k: Any) -> httpx.Response:
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "post", fake_post)
    with pytest.raises(LLMConfigError) as e:
        OllamaProvider("http://nope:1", "m").complete_json("s", "u", {})
    assert "neběží" in str(e.value)


def test_pricing() -> None:
    assert cost("claude-haiku-5-5", 1_000_000, 1_000_000) == pytest.approx(0.6)
    assert cost("unknown", 1, 1) is None
    h = estimate_hour("claude-sonnet-5-5", "cs")
    hk = estimate_hour("claude-haiku-5-5", "cs")
    assert h["usd"] > hk["usd"] > 0


# ---- finder (windows -> LLM -> clips) with a fake provider -------------------------------------

class FakeProvider(LLMProvider):
    name = "fake"
    model = "claude-haiku-5-5"

    def __init__(self, script: list[Any], local: bool = False) -> None:
        self.script = script
        self.calls = 0
        self.is_local = local
        self.prompts: list[str] = []

    def complete_json(self, system: str, user: str, schema: dict[str, Any], max_tokens: int = 16000) -> LLMResult:
        self.prompts.append(user)
        item = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        if isinstance(item, Exception):
            raise item
        if callable(item):
            return LLMResult(item(user), 100, 50)
        return LLMResult(item, 100, 50)

    def check(self) -> dict[str, Any]:
        return {"ok": True}


def words_long() -> list[dict[str, Any]]:
    text = " ".join(f"Tohle je věta číslo {i} o penězích a životě." for i in range(500))
    return make_words(text, wdur=0.3, gap=0.1, sentence_pause=0.3)


def clip_for_window(user: str) -> str:
    import re

    stamps = [float(x) for x in re.findall(r"\[(\d+\.\d+)-", user)]
    s = stamps[3]
    return json.dumps({"clips": [{**CLIP, "start": s, "end": s + 40, "title": f"Klip {s:.0f}"}]})


def test_find_moments_repairs_invalid_json_and_retries() -> None:
    settings = Settings(llm_window_minutes=10, llm_window_overlap_minutes=1.5, llm_max_retries=3, llm_concurrency=1)
    sleeps: list[float] = []
    prov = FakeProvider(["this is not json", LLMTransientError("rate", retry_after=2.0), clip_for_window])
    res = find_moments(words_long(), language="cs", length="30-60", focus="peníze", provider=prov,
                       settings=settings, sleep=sleeps.append)
    assert res.windows >= 2
    assert sleeps and sleeps[0] == 2.0
    assert len(res.candidates) >= 2
    assert all(30 * 0.8 <= c.duration <= 60.5 for c in res.candidates)
    assert any("not valid JSON" in p for p in prov.prompts), "repair prompt must be sent after invalid JSON"
    assert "peníze" in prov.prompts[0] and "Czech" in prov.prompts[0]
    assert res.cost_usd is not None and res.input_tokens > 0


def test_find_moments_config_error_aborts() -> None:
    prov = FakeProvider([LLMConfigError("Chybí API klíč")])
    with pytest.raises(LLMConfigError):
        find_moments(words_long(), language="cs", length="auto", focus=None, provider=prov,
                     settings=Settings(llm_concurrency=1), sleep=lambda s: None)


def test_find_moments_total_outage_raises_readable_error() -> None:
    prov = FakeProvider([LLMTransientError("down")])
    with pytest.raises(LLMError) as e:
        find_moments(words_long(), language="cs", length="auto", focus=None, provider=prov,
                     settings=Settings(llm_max_retries=2), sleep=lambda s: None)
    assert "nedostupný" in str(e.value)


def test_find_moments_partial_failure_warns() -> None:
    script: list[Any] = [clip_for_window, LLMTransientError("x"), LLMTransientError("x")]
    prov = FakeProvider(script)
    res = find_moments(words_long(), language="cs", length="30-60", focus=None, provider=prov,
                       settings=Settings(llm_max_retries=2, llm_window_minutes=10, llm_concurrency=1), sleep=lambda s: None)
    assert res.failed_windows >= 1 and res.warnings
    assert len(res.candidates) >= 1


def test_local_provider_gets_shorter_windows_and_follow_up() -> None:
    prov = FakeProvider([clip_for_window], local=True)
    res = find_moments(words_long(), language="cs", length="30-60", focus=None, provider=prov,
                       settings=Settings(llm_window_minutes=12, llm_concurrency=1), sleep=lambda s: None)
    assert res.windows >= 3  # 6-minute windows instead of 12
    assert any("ADDITIONAL" in p for p in prov.prompts), "follow-up request for more moments"

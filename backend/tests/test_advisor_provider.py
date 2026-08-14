from __future__ import annotations

import json
from collections.abc import Iterator

from app.core.config import Settings
from app.integrations.advisor import OpenAIResponsesProvider, _partial_answer, _structured_json_text


class FakeResponse:
    def __init__(self, *, body: object | None = None, lines: list[bytes] | None = None) -> None:
        self._body = body
        self._lines = lines or []

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._body).encode("utf-8")

    def __iter__(self) -> Iterator[bytes]:
        return iter(self._lines)


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        demo_mode=True,
        ai_enabled=True,
        openai_api_key="test-key",
        openai_model="gpt-5.6",
    )


def test_openai_plan_uses_store_false_and_strict_function_tools(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_request(self, payload, *, stream=False):
        captured.update(payload)
        assert stream is False
        return FakeResponse(
            body={
                "output": [
                    {
                        "type": "function_call",
                        "name": "evaluate_purchase",
                        "arguments": '{"amount":500}',
                    }
                ]
            }
        )

    monkeypatch.setattr(OpenAIResponsesProvider, "_request", fake_request)
    provider = OpenAIResponsesProvider(_settings())
    tools = [
        {
            "type": "function",
            "name": "evaluate_purchase",
            "description": "Read-only purchase check.",
            "parameters": {
                "type": "object",
                "properties": {"amount": {"type": "number"}},
                "required": ["amount"],
                "additionalProperties": False,
            },
            "strict": True,
        }
    ]
    calls = provider.plan(
        message="Can I afford $500?",
        mode="quick",
        snapshot={"safe_to_spend": "1200.00"},
        history=[],
        attached_insight=None,
        tools=tools,
        max_tool_calls=4,
    )

    assert calls == [{"name": "evaluate_purchase", "arguments": {"amount": 500}}]
    assert captured["model"] == "gpt-5.6"
    assert captured["tool_choice"] == "auto"
    assert captured["tools"] == tools


def test_openai_stream_uses_structured_output_and_streams_answer_field(monkeypatch) -> None:
    reply_json = (
        '{"mode":"quick","headline":"Fits the plan","answer": '
        '"Yes, based on Budget data.","confidence":"high","warnings":[],"suggested_questions":[],"action_plan_title":"","action_plan_summary":"","proposed_actions":[]}'
    )
    chunks = [reply_json[:70], reply_json[70:105], reply_json[105:]]
    lines = [
        ("data: " + json.dumps({"type": "response.output_text.delta", "delta": chunk}) + "\n").encode("utf-8")
        for chunk in chunks
    ]
    captured: dict[str, object] = {}

    def fake_request(self, payload, *, stream=False):
        captured.update(payload)
        assert stream is True
        return FakeResponse(lines=lines)

    monkeypatch.setattr(OpenAIResponsesProvider, "_request", fake_request)
    provider = OpenAIResponsesProvider(_settings())
    events = list(
        provider.stream_answer(
            message="Can I afford it?",
            mode="quick",
            snapshot={"cash": {"safe_to_spend": "1200.00"}},
            history=[],
            attached_insight=None,
            tool_results=[{"name": "evaluate_purchase", "result": {"fits_current_plan": True}}],
            facts=[{"label": "Safe to spend", "value": "USD 1,200.00", "detail": "Current month"}],
        )
    )

    streamed = "".join(str(value) for event, value in events if event == "delta")
    done = next(value for event, value in events if event == "done")
    assert streamed == "Yes, based on Budget data."
    assert done["answer"] == streamed
    assert captured["store"] is False
    assert captured["stream"] is True
    assert captured["text"]["format"]["type"] == "json_schema"
    assert captured["text"]["format"]["strict"] is True


def test_partial_answer_accepts_structured_json_whitespace() -> None:
    assert _partial_answer('{"answer" :  "hello') == "hello"


def _gemini_settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        demo_mode=True,
        ai_enabled=True,
        ai_provider="gemini",
        gemini_api_key="test-gemini-key",
        gemini_model="gemini-3.6-flash",
    )


def test_gemini_plan_uses_native_function_declarations(monkeypatch) -> None:
    from app.integrations.advisor import GeminiGenerateContentProvider

    captured: dict[str, object] = {}

    def fake_request(self, payload, *, stream=False):
        captured.update(payload)
        assert stream is False
        return FakeResponse(
            body={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "functionCall": {
                                        "name": "evaluate_purchase",
                                        "args": {"amount": 500},
                                    }
                                }
                            ]
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr(GeminiGenerateContentProvider, "_request", fake_request)
    provider = GeminiGenerateContentProvider(_gemini_settings())
    tools = [
        {
            "type": "function",
            "name": "evaluate_purchase",
            "description": "Read-only purchase check.",
            "parameters": {
                "type": "object",
                "properties": {"amount": {"type": "number"}},
                "required": ["amount"],
                "additionalProperties": False,
            },
            "strict": True,
        }
    ]
    calls = provider.plan(
        message="Can I afford $500?",
        mode="quick",
        snapshot={"safe_to_spend": "1200.00"},
        history=[],
        attached_insight=None,
        tools=tools,
        max_tool_calls=4,
    )

    assert calls == [{"name": "evaluate_purchase", "arguments": {"amount": 500}}]
    declaration = captured["tools"][0]["functionDeclarations"][0]
    assert declaration["name"] == "evaluate_purchase"
    assert declaration["parametersJsonSchema"] == tools[0]["parameters"]
    assert "strict" not in declaration
    assert captured["toolConfig"]["functionCallingConfig"]["mode"] == "AUTO"


def test_gemini_stream_uses_structured_json_and_streams_answer_field(monkeypatch) -> None:
    from app.integrations.advisor import GeminiGenerateContentProvider

    reply_json = (
        '{"mode":"quick","headline":"Fits the plan","answer": '
        '"Yes, based on Budget data.","confidence":"high","warnings":[],"suggested_questions":[],"action_plan_title":"","action_plan_summary":"","proposed_actions":[]}'
    )
    chunks = [reply_json[:70], reply_json[70:105], reply_json[105:]]
    lines = [
        (
            "data: "
            + json.dumps(
                {
                    "candidates": [
                        {"content": {"parts": [{"text": chunk}]}}
                    ]
                }
            )
            + "\n"
        ).encode("utf-8")
        for chunk in chunks
    ]
    captured: dict[str, object] = {}

    def fake_request(self, payload, *, stream=False):
        captured.update(payload)
        assert stream is True
        return FakeResponse(lines=lines)

    monkeypatch.setattr(GeminiGenerateContentProvider, "_request", fake_request)
    provider = GeminiGenerateContentProvider(_gemini_settings())
    events = list(
        provider.stream_answer(
            message="Can I afford it?",
            mode="quick",
            snapshot={"cash": {"safe_to_spend": "1200.00"}},
            history=[],
            attached_insight=None,
            tool_results=[{"name": "evaluate_purchase", "result": {"fits_current_plan": True}}],
            facts=[{"label": "Safe to spend", "value": "USD 1,200.00", "detail": "Current month"}],
        )
    )

    streamed = "".join(str(value) for event, value in events if event == "delta")
    done = next(value for event, value in events if event == "done")
    assert streamed == "Yes, based on Budget data."
    assert done["answer"] == streamed
    
    generation = captured["generationConfig"]
    assert generation["responseMimeType"] == "application/json"
    assert generation["responseJsonSchema"] == __import__("app.integrations.advisor", fromlist=["RESPONSE_SCHEMA"]).RESPONSE_SCHEMA
    assert generation["thinkingConfig"] == {"thinkingLevel": "low"}
    assert generation["maxOutputTokens"] == 6000


def test_gemini_stream_ignores_thought_parts_and_accepts_fenced_structured_json(monkeypatch) -> None:
    from app.integrations.advisor import GeminiGenerateContentProvider

    reply_json = (
        '{"mode":"analysis","headline":"Review this plan","answer":"Budget can preview it.",'
        '"confidence":"high","warnings":[],"suggested_questions":[],'
        '"action_plan_title":"Free up cash","action_plan_summary":"Trim flexible spending.",'
        '"proposed_actions":[{"action_type":"budget_category_monthly_set","target_id":4,'
        '"value":"500.00","secondary_value":"2026-08","rationale":"Reduce flexible spending."}]}'
    )
    wrapped = "```json\n" + reply_json + "\n```"
    chunks = [wrapped[:100], wrapped[100:220], wrapped[220:]]
    lines = []
    for index, chunk in enumerate(chunks):
        parts = [{"text": "internal thought that is not JSON", "thought": True}, {"text": chunk}]
        candidate = {"content": {"parts": parts}}
        if index == len(chunks) - 1:
            candidate["finishReason"] = "STOP"
        lines.append(("data: " + json.dumps({"candidates": [candidate]}) + "\n").encode("utf-8"))

    def fake_request(self, payload, *, stream=False):
        assert stream is True
        return FakeResponse(lines=lines)

    monkeypatch.setattr(GeminiGenerateContentProvider, "_request", fake_request)
    provider = GeminiGenerateContentProvider(_gemini_settings())
    events = list(
        provider.stream_answer(
            message="Build a plan",
            mode="analysis",
            snapshot={},
            history=[],
            attached_insight=None,
            tool_results=[],
            facts=[],
        )
    )
    done = next(value for event, value in events if event == "done")
    assert done["headline"] == "Review this plan"
    assert done["proposed_actions"][0]["target_id"] == 4


def test_structured_json_text_recovers_markdown_fence_only() -> None:
    assert _structured_json_text('```json\n{"answer":"ok"}\n```') == '{"answer":"ok"}'
    assert _structured_json_text('prefix {"answer":"ok"} suffix') == '{"answer":"ok"}'
    assert _structured_json_text('{"answer":"cut off"') == '{"answer":"cut off"'


def test_provider_for_settings_supports_gemini() -> None:
    from app.integrations.advisor import GeminiGenerateContentProvider, provider_for_settings

    assert isinstance(provider_for_settings(_gemini_settings()), GeminiGenerateContentProvider)

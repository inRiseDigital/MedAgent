"""Regression test for the chat "answer floor" (P0.1).

A tool-heavy request (e.g. "give me a full 360-degree profile") can finish with
an EMPTY final assistant turn — the ReAct loop hits the recursion cap, the model
truncates, or the last step is a tool/present_card call. Before the fix, the SSE
stream then carried zero `text-delta` frames and the UI rendered a silent blank
bubble. The contract now: every 200 stream emits at least one non-empty
`text-delta`, always.

These tests drive `/api/v1/chat` with a fake agent (no real LLM, no FHIR) so the
floor logic is exercised deterministically.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

import app.routers.chat as chat_module
from app.config import Settings
from app.main import create_app


class _FakeMsg:
    """Minimal stand-in for a LangChain message (chat.py reads .type/.content)."""

    def __init__(self, type_: str, content: str) -> None:
        self.type = type_
        self.content = content


class _FakeAgent:
    """Agent whose astream replays canned (mode, data) steps and records input."""

    def __init__(self, steps: list[tuple[str, Any]]) -> None:
        self._steps = steps
        self.received: list[dict[str, Any]] = []

    async def astream(self, agent_input: Any = None, *_a: Any, **_k: Any):  # noqa: ANN401
        if isinstance(agent_input, dict):
            self.received = agent_input.get("messages", [])
        for step in self._steps:
            yield step


def _app_with_agent(monkeypatch: pytest.MonkeyPatch, steps: list[tuple[str, Any]]) -> tuple[FastAPI, _FakeAgent]:
    # stub mode → skip the "no model key" short-circuit and reach the run path.
    app = create_app(Settings(auth_disabled=True, agent_llm_mode="stub"))
    agent = _FakeAgent(steps)
    monkeypatch.setattr(chat_module, "build_agent", lambda *a, **k: agent)

    async def _fake_resolve(*_a: Any, **_k: Any) -> str:
        return "patient-123"

    monkeypatch.setattr(chat_module, "resolve_patient_fhir_id", _fake_resolve)
    return app, agent


def _deltas(sse_text: str) -> list[str]:
    """All non-empty text-delta payloads from an SSE body."""
    out: list[str] = []
    for line in sse_text.splitlines():
        if not line.startswith("data: "):
            continue
        raw = line[len("data: ") :].strip()
        if not raw or raw == "[DONE]":
            continue
        try:
            evt = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if evt.get("type") == "text-delta" and evt.get("delta"):
            out.append(evt["delta"])
    return out


async def _post_chat(app: FastAPI, messages: list[dict[str, Any]] | None = None) -> str:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/chat",
            json={
                "messages": messages or [{"role": "user", "content": "give me a full 360-degree profile"}],
                "patient_id": "55246820131",
                "audience": "patient",
            },
        )
    assert resp.status_code == 200
    return resp.text


async def test_empty_run_still_emits_an_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    """The 360 case: agent ends with an empty AI message → floor must fire."""
    steps = [("values", {"messages": [_FakeMsg("ai", "")]})]
    app, _ = _app_with_agent(monkeypatch, steps)
    body = await _post_chat(app)
    deltas = _deltas(body)
    assert deltas, "stream carried NO text-delta — the blank-bubble regression is back"
    assert "".join(deltas).strip(), "text-delta was emitted but empty"
    assert "finish" in body and "[DONE]" in body


async def test_non_streaming_final_answer_passes_through(monkeypatch: pytest.MonkeyPatch) -> None:
    """OpenAI-compatible path: no token stream, answer only in the final values step."""
    steps = [("values", {"messages": [_FakeMsg("ai", "Here is your summary.")]})]
    app, _ = _app_with_agent(monkeypatch, steps)
    body = await _post_chat(app)
    assert "Here is your summary." in "".join(_deltas(body))


def test_looks_like_tool_leak_detects_hallucinated_calls() -> None:
    """The detector must catch a JSON tool-call emitted as text (Qwen on Groq does this
    when told not to use tools) without flagging genuine prose answers."""
    leak = chat_module._looks_like_tool_leak
    assert leak('{\n"tool": "get_record_overview",\n"arguments": {}\n}')  # the field report
    assert leak('```json\n{"name": "get_labs", "parameters": {"phn": "x"}}\n```')
    assert leak('{"function": "foo", "arguments": {}}')
    # Genuine answers must pass through untouched.
    assert not leak("Here are your active medications: Metformin, Atorvastatin.")
    assert not leak("Your potassium is critical [source: DiagnosticReport/1161].")
    assert not leak("")
    assert not leak('{"note": "plain data, not a tool call"}')  # JSON but no tool keys


async def test_leaked_tool_call_is_never_shown(monkeypatch: pytest.MonkeyPatch) -> None:
    """A model that ENDS the loop with a hallucinated tool-call as its 'final answer'
    must never have that raw JSON streamed to the user — the floor guard drops it and
    a graceful message stands instead (there is no record context in this harness, so
    the grounded recovery can't run, exercising the guard directly)."""
    leak = '{\n"tool": "get_record_overview",\n"arguments": {}\n}'
    steps = [("values", {"messages": [_FakeMsg("ai", leak)]})]
    app, _ = _app_with_agent(monkeypatch, steps)
    body = await _post_chat(app)
    joined = "".join(_deltas(body))
    assert "get_record_overview" not in joined and '"tool"' not in joined, "raw tool-call JSON leaked to the user"
    assert joined.strip(), "must still emit a graceful floor, never silence"


async def test_conversation_history_is_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    """History must not be dropped to the latest turn (multi-turn memory)."""
    steps = [("values", {"messages": [_FakeMsg("ai", "ok")]})]
    app, agent = _app_with_agent(monkeypatch, steps)
    convo = [
        {"role": "user", "content": "what are my allergies?"},
        {"role": "assistant", "content": "You have a penicillin allergy."},
        {"role": "user", "content": "is that serious?"},
    ]
    await _post_chat(app, convo)
    assert len(agent.received) == 3, f"history dropped: agent saw {len(agent.received)}/3"
    assert agent.received[0]["content"] == "what are my allergies?"

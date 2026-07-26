"""Deterministic offline chat model (backlog 0.3).

Streams a canned reply with **zero API calls** so the chat path can be
load-tested in CI and demoed when the LLM provider is unavailable or quota-capped.
`bind_tools` is a no-op, so the canned reply is the final answer (no tool calls) —
enough to exercise the full HTTP/stream/SSE path deterministically.

Selected by `AGENT_LLM_MODE=stub`; `live` (default) uses the real model.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator, Sequence
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

STUB_TEXT = (
    "**Offline demo mode — the live language model is not being called.**\n\n"
    "In live mode I read this patient's record through governed FHIR tools and put "
    "a citation on every clinical fact, and I can draft a prescription that the "
    "deterministic Rx-safety engine screens before you sign it.\n\n"
    "Record viewing, patient search and prescription safety are fully working right "
    "now — only the conversational narration is stubbed here."
)


def _chunks(text: str, per: int = 4) -> Iterator[str]:
    """Word-grouped chunks so the UI shows genuine streaming."""
    words = text.split(" ")
    for i in range(0, len(words), per):
        tail = " " if i + per < len(words) else ""
        yield " ".join(words[i : i + per]) + tail


class StubChatModel(BaseChatModel):
    """Offline, deterministic — never calls an external API."""

    text: str = STUB_TEXT

    @property
    def _llm_type(self) -> str:
        return "stub"

    # create_react_agent binds tools to the model; ignore them so the canned reply
    # is returned directly (no tool-calling round-trips).
    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "StubChatModel":
        return self

    def _msg(self) -> AIMessage:
        return AIMessage(content=self.text)

    def _generate(self, messages: list[BaseMessage], stop: list[str] | None = None,
                  run_manager: Any = None, **kwargs: Any) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._msg())])

    async def _agenerate(self, messages: list[BaseMessage], stop: list[str] | None = None,
                         run_manager: Any = None, **kwargs: Any) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._msg())])

    def _stream(self, messages: list[BaseMessage], stop: list[str] | None = None,
                run_manager: Any = None, **kwargs: Any) -> Iterator[ChatGenerationChunk]:
        for piece in _chunks(self.text):
            yield ChatGenerationChunk(message=AIMessageChunk(content=piece))

    async def _astream(self, messages: list[BaseMessage], stop: list[str] | None = None,
                       run_manager: Any = None, **kwargs: Any) -> AsyncIterator[ChatGenerationChunk]:
        for piece in _chunks(self.text):
            yield ChatGenerationChunk(message=AIMessageChunk(content=piece))

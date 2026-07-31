"""POST /api/v1/chat — streaming cited chat over the patient's FHIR record (04 §2).

Runs the patient-scoped LangGraph agent and adapts its token stream to the
**Vercel AI SDK data (UI message) protocol over SSE** — typed frames the web app
consumes with `useChat`. Citations gathered by the read tools are emitted as a
`data-citations` part so the UI can render source chips (FR-3.4).
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agent.build import build_agent, resolve_patient_fhir_id
from app.auth import Principal, require_user
from app.config import Settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    messages: list[dict[str, Any]] = Field(min_length=1)
    patient_id: str
    encounter_id: str | None = None


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _latest_user_text(messages: list[dict[str, Any]]) -> str:
    """Newest user message text, tolerating a plain `content` string or the AI SDK `parts` array."""
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str) and content.strip():
            return content
        text = "".join(
            p.get("text", "")
            for p in msg.get("parts", [])
            if isinstance(p, dict) and p.get("type") == "text"
        )
        if text.strip():
            return text
    return ""


def _delta_text(chunk: Any) -> str:
    """Pull text from an AIMessageChunk whose content may be a str or a block list."""
    content = getattr(chunk, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


@router.post("/chat")
async def chat(
    body: ChatRequest,
    request: Request,
    principal: Annotated[Principal, Depends(require_user)],
) -> StreamingResponse:
    settings: Settings = request.app.state.settings
    message_id = f"msg_{uuid.uuid4().hex}"
    text_id = f"txt_{uuid.uuid4().hex}"
    question = _latest_user_text(body.messages)

    async def stream() -> AsyncIterator[str]:
        yield _sse({"type": "start", "messageId": message_id})
        yield _sse({"type": "text-start", "id": text_id})

        def _fail(msg: str) -> list[str]:
            return [
                _sse({"type": "text-delta", "id": text_id, "delta": msg}),
                _sse({"type": "text-end", "id": text_id}),
                _sse({"type": "finish"}),
                "data: [DONE]\n\n",
            ]

        mode = settings.agent_llm_mode
        missing_key = (
            (mode == "live" and not settings.anthropic_api_key)
            or (mode == "openai" and not settings.llm_openai_api_key)
        )
        if missing_key:
            for f in _fail("Agent is not configured (no model key)."):
                yield f
            return

        fhir_id = await resolve_patient_fhir_id(settings.fhir_base_url, body.patient_id)
        if not fhir_id:
            for f in _fail(f"No FHIR record found for patient {body.patient_id}."):
                yield f
            return

        sources: list[dict[str, Any]] = []
        proposals: list[dict[str, Any]] = []
        agent = build_agent(settings, fhir_id, sources, proposals)
        try:
            # Provider-agnostic streaming. We ask for BOTH "messages" (token stream)
            # and "values" (full state per step). Anthropic streams the answer token
            # by token via "messages"; OpenAI-compatible providers (e.g. Groq) do NOT
            # stream the post-tool-call answer through langgraph, so those token
            # chunks are empty — for them we fall back to the final message content
            # from "values". `streamed` guards against emitting both (no duplication).
            streamed = False
            final_answer = ""
            async for mode, data in agent.astream(
                {"messages": [{"role": "user", "content": question}]},
                stream_mode=["messages", "values"],
            ):
                if mode == "messages":
                    token = data[0]
                    if token.__class__.__name__ == "AIMessageChunk":
                        delta = _delta_text(token)
                        if delta:
                            streamed = True
                            yield _sse({"type": "text-delta", "id": text_id, "delta": delta})
                elif mode == "values":
                    msgs = data.get("messages", []) if isinstance(data, dict) else []
                    if msgs and getattr(msgs[-1], "type", "") == "ai":
                        text = _delta_text(msgs[-1])
                        if text:
                            final_answer = text
            # Fallback for providers that didn't stream tokens: emit the answer once.
            if not streamed and final_answer:
                yield _sse({"type": "text-delta", "id": text_id, "delta": final_answer})
        except Exception as exc:  # noqa: BLE001 — never leak a stack trace to the UI
            logger.exception("agent run failed")
            m = str(exc).lower()
            if any(s in m for s in ("usage limit", "regain access", "rate limit", "429",
                                    "credit balance", "insufficient", "quota")):
                # Not a code fault — the LLM provider is capped. Retrying won't help,
                # so say so honestly instead of "please retry".
                note = (
                    "\n\n[The AI assistant is temporarily unavailable — the language-model "
                    "service usage limit has been reached. Record viewing, search and "
                    "prescription safety are unaffected. Please try the assistant again later.]"
                )
            else:
                note = "\n\n[The assistant hit an error. Please retry.]"
            yield _sse({"type": "text-delta", "id": text_id, "delta": note})

        yield _sse({"type": "text-end", "id": text_id})
        if sources:  # citation chips (FR-3.4): resources the tools read
            yield _sse({"type": "data-citations", "data": sources})
        if proposals:  # write-intent drafts → sign-off cards (04 §2.2)
            yield _sse({"type": "data-proposals", "data": proposals})
        yield _sse({"type": "finish"})
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "x-vercel-ai-ui-message-stream": "v1",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )

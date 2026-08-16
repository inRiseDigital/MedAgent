"""POST /api/v1/chat — streaming cited chat over the patient's FHIR record (04 §2).

Runs the patient-scoped LangGraph agent and adapts its token stream to the
**Vercel AI SDK data (UI message) protocol over SSE** — typed frames the web app
consumes with `useChat`. Citations gathered by the read tools are emitted as a
`data-citations` part so the UI can render source chips (FR-3.4).
"""

from __future__ import annotations

import asyncio
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
    # Persona hint: "patient" → warm, plain-language concierge; anything else →
    # clinician briefing. Not a security boundary — data access is patient-scoped
    # by fhir_id regardless — only the tone/framing of the narration changes.
    audience: str = "clinician"
    # UI locale: the assistant replies in this language (en | si | ta).
    locale: str = "en"


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
        cards: list[dict[str, Any]] = []
        agent = build_agent(settings, fhir_id, sources, proposals, audience=body.audience, cards=cards, locale=body.locale)

        # State tracked across the run so we can GUARANTEE an answer floor: every
        # 200 stream must carry at least one text-delta. A tool-heavy request (e.g.
        # "give me a full 360 profile") can otherwise finish with an empty final
        # assistant turn (recursion cap / token truncation / a trailing tool or
        # present_card call) and render a silent blank bubble.
        streamed = False  # at least one token was streamed to the client
        final_answer = ""  # last non-empty AI message content (non-streaming providers)
        errored = False  # an error note was already emitted as the reply
        timed_out = False
        try:
            # Provider-agnostic streaming. We ask for BOTH "messages" (token stream)
            # and "values" (full state per step). Anthropic streams the answer token
            # by token via "messages"; OpenAI-compatible providers (e.g. Groq) do NOT
            # stream the post-tool-call answer through langgraph, so those token
            # chunks are empty — for them we fall back to the final message content
            # from "values". `streamed` guards against emitting both (no duplication).
            async with asyncio.timeout(settings.agent_run_timeout_seconds):
                async for mode, data in agent.astream(
                    {"messages": [{"role": "user", "content": question}]},
                    stream_mode=["messages", "values"],
                    config={"recursion_limit": settings.agent_recursion_limit},
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
        except (TimeoutError, asyncio.TimeoutError):
            timed_out = True
            logger.warning("agent run exceeded %ss", settings.agent_run_timeout_seconds)
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
            errored = True
            yield _sse({"type": "text-delta", "id": text_id, "delta": note})

        # ANSWER FLOOR — the stream must never be silent. Priority: streamed tokens
        # (nothing to do) → non-streaming provider's final answer → a graceful
        # message so the user always sees something actionable.
        if not streamed and not errored:
            if final_answer:
                yield _sse({"type": "text-delta", "id": text_id, "delta": final_answer})
            else:
                if timed_out:
                    floor = (
                        "This is taking longer than expected. Please try again, or ask "
                        "about one thing at a time (for example your medications, "
                        "allergies, or latest results)."
                    )
                else:
                    floor = (
                        "I looked into the record but couldn't put together a full answer "
                        "in one go. Please try again, or ask about one area at a time — "
                        "medications, allergies, or recent results."
                    )
                if sources:
                    floor += f"\n\n(Reviewed {len(sources)} record source(s).)"
                yield _sse({"type": "text-delta", "id": text_id, "delta": floor})

        yield _sse({"type": "text-end", "id": text_id})
        if sources:  # citation chips (FR-3.4): resources the tools read
            yield _sse({"type": "data-citations", "data": sources})
        if proposals:  # write-intent drafts → sign-off cards (04 §2.2)
            yield _sse({"type": "data-proposals", "data": proposals})
        if cards:  # generative-UI summary cards (present_card) rendered by the client
            yield _sse({"type": "data-cards", "data": cards})
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

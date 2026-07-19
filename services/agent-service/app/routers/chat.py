"""POST /api/v1/chat — streaming chat endpoint (04 §2.4).

Stream format: **Vercel AI SDK data (UI message) protocol over SSE** — typed
frames (`text-start`/`text-delta`/`text-end`/`finish`) that the web app
consumes with `useChat` (ADR AG-4: EventSource-style raw SSE cannot carry
typed tool/proposal/citation frames).

S1: echoes a stub token stream so the transport is real end-to-end. Real LLM
wiring (LangGraph `astream_events` → this adapter, Anthropic pinned model) is
Sprint S3.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.auth import Principal, require_user
from app.graph.state import ChatMessage

router = APIRouter(tags=["chat"])

_STUB_ANSWER = (
    "This is the S1 skeleton token stream from agent-service. "
    "The orchestrator graph exists but is not wired to the record or the LLM yet; "
    "cited answers arrive in Sprint S3."
)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1)
    patient_id: str
    encounter_id: str | None = None


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload)}\n\n"


@router.post("/chat")
async def chat(
    body: ChatRequest,
    principal: Annotated[Principal, Depends(require_user)],
) -> StreamingResponse:
    """Stream a (stubbed) assistant turn in AI SDK data-protocol frames.

    TODO(S3): stamp AgentState from the verified token + body, run
    build_graph().astream_events(...), adapt events to text/tool/citation
    frames, record per-run cost telemetry (04 §4).
    """
    message_id = f"msg_{uuid.uuid4().hex}"
    text_id = f"txt_{uuid.uuid4().hex}"

    async def token_stream() -> AsyncIterator[str]:
        yield _sse({"type": "start", "messageId": message_id})
        yield _sse({"type": "text-start", "id": text_id})
        for word in _STUB_ANSWER.split(" "):
            yield _sse({"type": "text-delta", "id": text_id, "delta": word + " "})
            await asyncio.sleep(0.02)  # visible streaming in dev; removed with real tokens
        yield _sse({"type": "text-end", "id": text_id})
        yield _sse({"type": "finish"})
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        token_stream(),
        media_type="text/event-stream",
        headers={
            "x-vercel-ai-ui-message-stream": "v1",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )

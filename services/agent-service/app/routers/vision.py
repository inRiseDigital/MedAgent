"""POST /api/v1/vision — multimodal image understanding (P4b).

The person shares a photo (lab report, prescription, medicine box, symptom); the
agent reads it on a vision-capable model and explains it in the persona's voice,
streamed over the SAME Vercel-AI-SDK SSE frame protocol as /chat so the web app
reuses its stream reader. The image is never treated as the patient's cited
record, and the agent does not diagnose (see app/agent/vision.py).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agent.context import build_patient_context
from app.agent.vision import stream_image_analysis, validate_image
from app.auth import Principal, require_user
from app.config import Settings
from app.routers.chat import _sse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["vision"])


class VisionRequest(BaseModel):
    patient_id: str
    image_base64: str = Field(min_length=1)
    mime: str = "image/jpeg"
    question: str = ""
    audience: str = "clinician"
    locale: str = "en"


@router.post("/vision")
async def vision(
    body: VisionRequest,
    request: Request,
    principal: Annotated[Principal, Depends(require_user)],
) -> StreamingResponse:
    settings: Settings = request.app.state.settings
    text_id = f"txt_{uuid.uuid4().hex}"

    async def stream() -> AsyncIterator[str]:
        yield _sse({"type": "start", "messageId": f"msg_{uuid.uuid4().hex}"})
        yield _sse({"type": "text-start", "id": text_id})

        err = validate_image(body.image_base64, body.mime)
        if err:
            yield _sse({"type": "text-delta", "id": text_id, "delta": err})
        else:
            # Best-effort record context for grounding the framing (never mixed into
            # the image reading itself — the vision prompt keeps them separate).
            context_text = await build_patient_context(
                settings.core_api_base_url, request.headers.get("authorization"), body.patient_id
            )
            streamed = False
            async for piece in stream_image_analysis(
                settings, body.image_base64, body.mime, body.question,
                body.audience, body.locale, context_text,
            ):
                if piece:
                    streamed = True
                    yield _sse({"type": "text-delta", "id": text_id, "delta": piece})
            if not streamed:
                yield _sse({"type": "text-delta", "id": text_id,
                            "delta": "I couldn't read that image — please try another photo."})

        yield _sse({"type": "text-end", "id": text_id})
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

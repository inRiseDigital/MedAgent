"""Multimodal image understanding (P4b).

The patient/doctor shares an image — a photo of a lab report, a prescription, a
medicine box, an ECG strip, or a visible symptom — and the agent reads it and
explains it in the persona's voice. Vision runs on a vision-capable model
(Anthropic Claude) regardless of the configured text chat model (Groq Qwen is
text-only), so this path always uses Claude even when `agent_llm_mode != "live"`.

Hard boundaries (same discipline as the rest of the agent):
- The image is NOT the patient's cited FHIR record. Findings are described as
  "from the image you shared" and never mixed into [source: …] record citations.
- No diagnosis / no treatment decisions — clinical calls stay with the clinician.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from app.config import Settings

logger = logging.getLogger(__name__)

_ALLOWED_MIME = {"image/png", "image/jpeg", "image/webp", "image/gif"}
_MAX_B64 = 7_000_000  # ~5 MB raw; Anthropic caps images and we keep requests small

_PATIENT_PROMPT = (
    "You are a warm, reassuring health concierge speaking DIRECTLY to a patient (say 'you'/'your'). "
    "They shared an image — often a photo of a lab report, a prescription or medicine box, or a visible "
    "symptom. In plain, kind, low-reading-level language:\n"
    "- Say what you can SEE and READ in the image. If it's a report or label, list the values/names you can "
    "make out.\n"
    "- Be calm and reassuring. If something looks like it needs attention, say so gently and encourage them "
    "to check with their doctor or care team.\n"
    "HARD RULES: Do NOT diagnose, do NOT say what's wrong, do NOT give treatment or medication decisions — "
    "those are for their doctor. This is what you can read from the IMAGE they shared; it is NOT their medical "
    "record. If the image is unclear or not health-related, say so kindly. A tasteful emoji is fine."
)

_CLINICIAN_PROMPT = (
    "You are a concise clinical assistant. The doctor shared an image — a lab report, imaging, an ECG strip, "
    "a wound/skin photo, or a document. Objectively describe and EXTRACT what is visible: values, labels, "
    "units, dates, and obvious features. Use short bullets/tables. Mark any interpretation, differential, or "
    "guideline context as [general knowledge]. Do NOT make final clinical decisions. This is read from the "
    "IMAGE the doctor shared — it is NOT the patient's cited record; keep it separate from [source: …] facts."
)

_LANG = {"si": "Sinhala (සිංහල)", "ta": "Tamil (தமிழ்)"}


def validate_image(image_base64: str, mime: str) -> str | None:
    """Return an error string if the image is unusable, else None."""
    if mime not in _ALLOWED_MIME:
        return f"Unsupported image type '{mime}'. Please share a PNG, JPEG, WEBP or GIF."
    if not image_base64 or len(image_base64) > _MAX_B64:
        return "That image is too large — please share a smaller photo (under ~5 MB)."
    return None


async def stream_image_analysis(
    settings: Settings,
    image_base64: str,
    mime: str,
    question: str,
    audience: str,
    locale: str = "en",
    context_text: str = "",
) -> AsyncIterator[str]:
    """Stream a plain-language reading of the shared image, in the persona's voice.

    Always uses the Anthropic vision model (the OpenAI-compatible text model may be
    text-only). Yields text chunks; on any error yields a single graceful line.
    """
    from langchain_anthropic import ChatAnthropic
    from langchain_core.messages import HumanMessage, SystemMessage

    if not settings.anthropic_api_key:
        yield "I can't look at images right now — image understanding isn't configured."
        return

    prompt = _PATIENT_PROMPT if audience == "patient" else _CLINICIAN_PROMPT
    if context_text:
        prompt += (
            "\n\nFor context only (the person's record — do NOT treat the image as part of it): "
            + context_text
        )
    if locale in _LANG:
        prompt += f"\n\nWrite your entire reply in {_LANG[locale]}, in clear everyday language."

    ask = (question or "").strip() or (
        "Please look at this image and tell me what you can see and read in it."
    )
    llm = ChatAnthropic(
        model=settings.anthropic_model,
        api_key=settings.anthropic_api_key,
        max_tokens=settings.agent_max_tokens,
        max_retries=settings.llm_max_retries,
        default_request_timeout=settings.llm_timeout_seconds,
        thinking={"type": "disabled"},
    )
    messages = [
        SystemMessage(content=prompt),
        HumanMessage(content=[
            {"type": "text", "text": ask},
            {"type": "image", "source": {"type": "base64", "media_type": mime, "data": image_base64}},
        ]),
    ]
    try:
        async for chunk in llm.astream(messages):
            content = getattr(chunk, "content", "")
            if isinstance(content, str):
                if content:
                    yield content
            elif isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "text" and b.get("text"):
                        yield b["text"]
    except Exception:  # noqa: BLE001 — never leak a stack trace to the UI
        logger.exception("image analysis failed")
        yield "\n\nSorry — I couldn't read that image just now. Please try another photo."

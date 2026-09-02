"""POST /api/v1/consult/agenda — the doctor consult session (Horizon-1 / S6).

When a clinician starts a consultation, the agent produces a GROUNDED agenda of
items to work through — reason for visit, active problems, medications to
reconcile, results to discuss, and follow-ups — each cited from the record. The
doctor confirms each item in the UI before it counts (the "confirm each thing"
flow); a session summary is assembled from the confirmed items.

The agenda is derived DETERMINISTICALLY from the same pre-loaded, cited context
the chat grounds on (app/agent/context.py), so every item carries a [source: …]
reference and nothing is invented — the same grounding discipline as the rest of
the platform. (An LLM pass to add a narrative "reason for visit" and priority
ordering is a follow-up.)
"""

from __future__ import annotations

import logging
import re
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.agent.context import build_patient_context
from app.auth import Principal, require_user
from app.config import Settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["consult"])

_SOURCE_RE = re.compile(r"\[source:\s*([A-Za-z]+/[A-Za-z0-9._-]+)\]")


class ConsultRequest(BaseModel):
    patient_id: str
    audience: str = "clinician"
    locale: str = "en"


def _section(context_text: str, label: str) -> str:
    """The '- <label>: …' line body from the cited context, or ''."""
    for line in context_text.splitlines():
        s = line.strip().lstrip("- ")
        if s.lower().startswith(label.lower() + ":"):
            return s[len(label) + 1:].strip().rstrip(".")
    return ""


def _items_from(section: str, item_type: str, start: int) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for raw in section.split(";"):
        raw = raw.strip()
        if not raw:
            continue
        m = _SOURCE_RE.search(raw)
        ref = m.group(1) if m else None
        label = _SOURCE_RE.sub("", raw).strip().rstrip(" .")
        if not label:
            continue
        item: dict[str, str] = {"id": f"item-{start + len(out)}", "type": item_type, "label": label[:140]}
        if ref:
            item["ref"] = ref
        out.append(item)
    return out


def build_agenda(context_text: str) -> list[dict[str, str]]:
    """A grounded, cited consultation agenda from the pre-loaded context."""
    items: list[dict[str, str]] = [
        {"id": "item-0", "type": "reason", "label": "Confirm the reason for today's visit"},
    ]
    # Safety flags first — the things to review before anything else.
    flags = _section(context_text, "SAFETY FLAGS (deterministic)")
    if flags:
        items += _items_from(flags, "result", len(items))
    for label, kind in (
        ("Active problems", "problem"),
        ("Active medications", "medication"),
        ("Recent results", "result"),
    ):
        sec = _section(context_text, label)
        if sec:
            items += _items_from(sec, kind, len(items))
    appts = _section(context_text, "Appointments")
    if appts:
        items += _items_from(appts, "followup", len(items))
    return items


@router.post("/consult/agenda")
async def consult_agenda(
    body: ConsultRequest,
    request: Request,
    principal: Annotated[Principal, Depends(require_user)],
) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    context_text = await build_patient_context(
        settings.core_api_base_url, request.headers.get("authorization"), body.patient_id
    )
    if not context_text:
        return {"items": [{"id": "item-0", "type": "reason",
                           "label": "Confirm the reason for today's visit"}], "grounded": False}
    return {"items": build_agenda(context_text), "grounded": True}

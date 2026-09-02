"""File a completed consult session to the record (Horizon-1 / S7 write-back).

When a doctor completes a consult, the confirmed agenda items become a real,
gated FHIR write: a finished `Encounter` (ambulatory) plus a clinical note
(`DocumentReference`) summarising the confirmed items, so the session is on the
record. Every write is audited via the outbox — same path as proposals.py.
"""

from __future__ import annotations

import base64
import logging
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import Principal, require_roles, require_user
from app.config import Settings
from app.deps import get_session, get_settings
from app.fhir_client import FHIRClient
from app.fhir.helpers import (
    bearer as _bearer,
    resolve_patient_id as _resolve_patient,
)
from app.models import AuditOutbox

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/consult", tags=["write-back"])

AMB_CLASS = {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "AMB"}


class ConsultRequest(BaseModel):
    patient: str = Field(min_length=1, description="PHN or FHIR Patient id")
    items: list[str] = []  # the confirmed agenda item labels
    note: str | None = None  # optional drafted prose note
    reason: str | None = None


def _note_text(note: str | None, items: list[str]) -> str:
    """The note prose to file. Always includes the confirmed item list; if a
    drafted prose note is supplied it is kept and the item list appended."""
    summary = "\n".join(
        ["Consultation — items addressed:"] + [f"- {it}" for it in items]
    )
    if note:
        return f"{note}\n\n{summary}"
    return summary


@router.post(
    "/encounter",
    status_code=status.HTTP_201_CREATED,
    dependencies=[require_roles("doctor")],
)
async def file_encounter(
    body: ConsultRequest,
    request: Request,
    principal: Annotated[Principal, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    token = _bearer(request)
    fhir = FHIRClient(settings.fhir_base_url)
    try:
        pid = await _resolve_patient(fhir, body.patient)
        if not pid:
            raise HTTPException(status_code=404, detail=f"no FHIR patient for {body.patient}")

        now = datetime.now(timezone.utc).isoformat()
        subject = {"reference": f"Patient/{pid}"}

        encounter: dict[str, Any] = {
            "resourceType": "Encounter",
            "status": "finished",
            "class": AMB_CLASS,
            "subject": subject,
            "participant": [{"individual": {"display": principal.subject}}],
            "period": {"start": now},
        }
        if body.reason:
            encounter["reasonCode"] = [{"text": body.reason}]
        enc_created = await fhir.create("Encounter", encounter, token)
        enc_ref = f"Encounter/{enc_created.get('id')}"

        text = _note_text(body.note, body.items)
        data = base64.b64encode(text.encode("utf-8")).decode("ascii")
        document: dict[str, Any] = {
            "resourceType": "DocumentReference",
            "status": "current",
            "type": {"text": "Consultation note"},
            "subject": subject,
            "date": now,
            "author": [{"display": principal.subject}],
            "context": {"encounter": [{"reference": enc_ref}]},
            "content": [{"attachment": {"contentType": "text/plain", "data": data}}],
        }
        doc_created = await fhir.create("DocumentReference", document, token)
        doc_ref = f"DocumentReference/{doc_created.get('id')}"

        for ref in (enc_ref, doc_ref):
            session.add(AuditOutbox(event={
                "type": "consult_filed",
                "actor": principal.subject,
                "patient_fhir_id": pid,
                "committed": ref,
            }))
        logger.info("consult filed", extra={"encounter": enc_ref, "document": doc_ref})
        return {"encounter_id": enc_ref, "document_id": doc_ref}
    finally:
        await fhir.close()

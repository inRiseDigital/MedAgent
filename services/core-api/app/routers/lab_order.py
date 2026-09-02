"""File a lab order as a gated FHIR ServiceRequest (new capability).

A doctor orders a lab test from the copilot; this files it as a real, gated FHIR
`ServiceRequest` (laboratory procedure) so it enters the lab workflow. The write
is audited via the outbox — same path as consult.py / proposals.py.
"""

from __future__ import annotations

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

router = APIRouter(prefix="/lab", tags=["write-back"])

LAB_CATEGORY = {
    "coding": [{
        "system": "http://snomed.info/sct",
        "code": "108252007",
        "display": "Laboratory procedure",
    }]
}


class LabOrderRequest(BaseModel):
    patient: str = Field(min_length=1, description="PHN or FHIR Patient id")
    test: str = Field(min_length=1, description="the lab test name, e.g. 'Full blood count'")
    priority: str | None = None  # "routine" (default) | "urgent" | "stat"


@router.post(
    "/order",
    status_code=status.HTTP_201_CREATED,
    dependencies=[require_roles("doctor")],
)
async def create_lab_order(
    body: LabOrderRequest,
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
        service_request: dict[str, Any] = {
            "resourceType": "ServiceRequest",
            "status": "active",
            "intent": "order",
            "priority": body.priority or "routine",
            "category": [LAB_CATEGORY],
            "code": {"text": body.test},
            "subject": {"reference": f"Patient/{pid}"},
            "authoredOn": now,
            "requester": {"display": principal.subject},
        }
        created = await fhir.create("ServiceRequest", service_request, token)
        ref = f"ServiceRequest/{created.get('id')}"

        session.add(AuditOutbox(event={
            "type": "lab_order_created",
            "actor": principal.subject,
            "patient_fhir_id": pid,
            "committed": ref,
        }))
        logger.info("lab order created", extra={"service_request": ref, "test": body.test})
        return {"service_request_id": ref, "test": body.test}
    finally:
        await fhir.close()

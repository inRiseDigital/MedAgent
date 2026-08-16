"""Patient consent management (FR-5.2, 03 §5.2).

A patient toggles a consent category (Phase A: face-recognition). The write
updates three things atomically-ish: the MPI `face_consent` flag (which the face
webhook gate reads, 05 §3), a FHIR `Consent` resource (the versioned source of
truth + history), and an audit row; it then publishes a cache-invalidation so the
change takes effect within a round-trip, not a TTL (03 §5.2). Patients may only
change their own consent (self-check on the `phn` claim).
"""

from __future__ import annotations

import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import Principal, require_user
from app.config import Settings
from app.deps import get_redis, get_session, get_settings
from app.fhir_client import FHIRClient
from app.fhir.helpers import PHN_SYSTEM
from app.models import AuditOutbox, PatientMPI

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/patients", tags=["consent"])

CONSENT_CATEGORY_SYSTEM = "https://fhir.medagent.health.lk/cs/consent-category"


class ConsentState(BaseModel):
    face_recognition: bool


def _self_guard(principal: Principal, phn: str) -> None:
    """A patient may only read/change their own consent."""
    if principal.has_role("patient"):
        claim = str(principal.claims.get("phn", ""))
        if claim and claim != phn:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not your record")


async def _mpi_row(session: AsyncSession, phn: str) -> PatientMPI:
    row = (await session.execute(select(PatientMPI).where(PatientMPI.phn == phn))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="unknown patient")
    return row


@router.get("/{phn}/consent", response_model=ConsentState)
async def get_consent(
    phn: str,
    principal: Annotated[Principal, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ConsentState:
    _self_guard(principal, phn)
    row = await _mpi_row(session, phn)
    return ConsentState(face_recognition=row.face_consent)


@router.put("/{phn}/consent", response_model=ConsentState)
async def set_consent(
    phn: str,
    body: ConsentState,
    principal: Annotated[Principal, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> ConsentState:
    _self_guard(principal, phn)
    row = await _mpi_row(session, phn)
    row.face_consent = body.face_recognition

    # Versioned FHIR Consent (source of truth + history).
    fhir = FHIRClient(settings.fhir_base_url)
    try:
        matches = await fhir.search("Patient", {"identifier": f"{PHN_SYSTEM}|{phn}"})
        if matches:
            pid = matches[0]["id"]
            consent: dict[str, Any] = {
                "resourceType": "Consent",
                "status": "active",
                "scope": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/consentscope",
                                      "code": "patient-privacy"}]},
                "category": [{"coding": [{"system": CONSENT_CATEGORY_SYSTEM, "code": "face-recognition"}]}],
                "patient": {"reference": f"Patient/{pid}"},
                "provision": {"type": "permit" if body.face_recognition else "deny"},
            }
            await fhir.create("Consent", consent)
    finally:
        await fhir.close()

    session.add(AuditOutbox(event={
        "type": "consent_change",
        "actor": principal.subject,
        "patient_fhir_id": None,
        "category": "face-recognition",
        "granted": body.face_recognition,
        "phn_last4": phn[-4:],
    }))

    # Invalidate the consent decision cache so the change is immediate (03 §5.2).
    await redis.publish("events:consent:invalidate", json.dumps({"phn": phn, "category": "face-recognition"}))
    logger.info("consent updated", extra={"category": "face-recognition", "granted": body.face_recognition})
    return ConsentState(face_recognition=body.face_recognition)

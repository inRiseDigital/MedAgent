"""Inbound face-service match-event webhook — hardened per 05 §3.

Enforcement order (05 §3): signature + freshness → idempotency → resolution →
consent gate (authoritative) → threshold policy → effect. The endpoint returns
**202 Accepted for every authenticated event** regardless of outcome, so an
observer at the kiosk cannot distinguish a consent-denied drop from a normal
acceptance.
"""

from __future__ import annotations

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, ValidationError
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.deps import get_redis, get_session, get_settings
from app.events import publish_checkin
from app.models import AuditOutbox, CheckinSource, PatientMPI, QueueEntry, QueueState
from app.webhook_security import WebhookVerificationError, verify_webhook

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations/face", tags=["integrations"])

IDEMPOTENCY_KEY_TEMPLATE = "face:event:{event_id}"


class FaceEvent(BaseModel):
    """Webhook body per 05 §3."""

    event_id: str = Field(description="idempotency key (uuid)")
    event_type: Literal["match", "no_match", "liveness_fail"]
    ext_face_id: str | None = Field(default=None, description="opaque enrolment id (match only)")
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    liveness: Literal["pass", "fail", "not_performed"] = "not_performed"
    station_id: str
    facility_id: str
    occurred_at: str


class FaceEventAck(BaseModel):
    status: str


@router.post(
    "/events",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=FaceEventAck,
)
async def face_event_webhook(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    redis: Annotated[Redis, Depends(get_redis)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FaceEventAck:
    raw_body = await request.body()

    # 1. Signature + freshness (05 §3 step 1). HMAC over timestamp + "." + raw body.
    try:
        verify_webhook(
            signature=request.headers.get("X-MedAgent-Signature"),
            timestamp=request.headers.get("X-MedAgent-Timestamp"),
            key_id=request.headers.get("X-MedAgent-Key-Id"),
            raw_body=raw_body,
            keys=settings.face_webhook_hmac_keys,
            tolerance_seconds=settings.face_webhook_tolerance_seconds,
        )
    except WebhookVerificationError as exc:
        # Signature-failure spikes are an alert condition (10 §6.3).
        logger.warning("face webhook rejected", extra={"reason": exc.reason})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="webhook verification failed"
        ) from exc

    try:
        event = FaceEvent.model_validate_json(raw_body)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="malformed event"
        ) from exc

    # 2. Idempotency: duplicate event_id within 24 h → 202, no effect (Redis SETNX).
    fresh = await redis.set(
        IDEMPOTENCY_KEY_TEMPLATE.format(event_id=event.event_id),
        "1",
        nx=True,
        ex=settings.face_event_idempotency_ttl_seconds,
    )
    if not fresh:
        logger.info("duplicate face event ignored", extra={"event_id": event.event_id})
        return FaceEventAck(status="duplicate")

    # TODO(S2): per-station rate limit (05 §3 step 3).

    outcome = await _process_event(event, session=session, redis=redis, settings=settings)
    return FaceEventAck(status=outcome)


async def _process_event(
    event: FaceEvent,
    *,
    session: AsyncSession,
    redis: Redis,
    settings: Settings,
) -> str:
    """Steps 4–7 of 05 §3: resolve → consent gate → threshold policy → effect."""
    if event.event_type != "match" or not event.ext_face_id:
        # no_match / liveness_fail drive the reception assist view (S2 UI work).
        session.add(
            AuditOutbox(
                event={
                    "type": f"face_{event.event_type}",
                    "event_id": event.event_id,
                    "station_id": event.station_id,
                    "facility_id": event.facility_id,
                }
            )
        )
        return "logged"

    # 4. Resolution: ext_face_id → MPI patient.
    patient = (
        await session.execute(
            select(PatientMPI).where(PatientMPI.ext_face_id == event.ext_face_id)
        )
    ).scalar_one_or_none()
    if patient is None:
        # Unknown ID → logged; alert on threshold (possible desync or probe).
        logger.warning(
            "unknown ext_face_id in face event",
            extra={"event_id": event.event_id, "station_id": event.station_id},
        )
        session.add(
            AuditOutbox(
                event={
                    "type": "face_unknown_ext_face_id",
                    "event_id": event.event_id,
                    "station_id": event.station_id,
                    "facility_id": event.facility_id,
                }
            )
        )
        return "unknown_ext_face_id"

    # 5. Consent gate (authoritative): no active consent → silent drop + audit.
    #    Nothing is surfaced to any user or queue. TODO(S2): also check the FHIR
    #    Consent resource (face-recognition scope) + push suppression list (05 §4).
    if not patient.face_consent:
        session.add(
            AuditOutbox(
                event={
                    "type": "consent_denied",
                    "event_id": event.event_id,
                    "patient_id": str(patient.id),
                    "station_id": event.station_id,
                    "facility_id": event.facility_id,
                }
            )
        )
        logger.info("face event dropped (consent)", extra={"event_id": event.event_id})
        return "dropped"

    # 6. Policy gate: confidence threshold (facility config, FR-6.2 — env default in S1).
    #    TODO(S2): liveness == "pass" required, legacy-station carve-out (05 §3 step 6).
    if event.confidence < settings.face_confidence_threshold:
        entry = QueueEntry(
            patient_id=patient.id,
            facility_id=event.facility_id,
            state=QueueState.manual_verification,
            source=CheckinSource.face,
        )
        session.add(entry)
        await session.flush()
        session.add(
            AuditOutbox(
                event={
                    "type": "face_manual_verification",
                    "event_id": event.event_id,
                    "patient_id": str(patient.id),
                    "queue_entry_id": str(entry.id),
                    "facility_id": event.facility_id,
                    "confidence": event.confidence,
                }
            )
        )
        return "manual_verification"

    # 7. Effect: enqueue + audit + publish to the facility's check-in channel.
    entry = QueueEntry(
        patient_id=patient.id,
        facility_id=event.facility_id,
        state=QueueState.waiting,
        source=CheckinSource.face,
    )
    session.add(entry)
    await session.flush()
    session.add(
        AuditOutbox(
            event={
                "type": "checkin",
                "source": "face",
                "event_id": event.event_id,
                "patient_id": str(patient.id),
                "queue_entry_id": str(entry.id),
                "facility_id": event.facility_id,
            }
        )
    )
    await publish_checkin(
        redis,
        event.facility_id,
        {
            "type": "checkin",
            "queue_entry_id": str(entry.id),
            "patient_id": str(patient.id),
            "facility_id": event.facility_id,
            "source": "face",
        },
    )
    return "checked_in"

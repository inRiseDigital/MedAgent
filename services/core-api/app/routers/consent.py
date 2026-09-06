"""Patient consent management (FR-5.2, 03 §5.2).

Two consent surfaces live here:

* **Biometric (face-recognition)** — Phase A. Toggling it flips the MPI
  ``face_consent`` gate (read by the face webhook, 05 §3) AND writes a versioned
  FHIR ``Consent`` (category=face-recognition). This governs kiosk check-in, NOT
  record visibility, so the FHIR ``ConsentInterceptor`` deliberately excludes it
  from masking. (Back-compat: the PUT body ``{"face_recognition": bool}`` and the
  GET field ``face_recognition`` are unchanged.)

* **Per-purpose record sharing** — a patient may allow or deny sharing their
  record for a specific PURPOSE (treatment / research / marketing) *independently*.
  Each purpose is its own versioned FHIR ``Consent`` carrying a
  ``provision.purpose`` PurposeOfUse code; a ``deny`` for TREAT masks only
  treatment-purpose reads, a ``deny`` for HRESCH masks only research reads, etc.
  (the ``ConsentInterceptor`` evaluates the deny against the request's
  ``X-MedAgent-Purpose``). The default is ALLOW — the absence of a deny provision
  never masks data, so adding this surface cannot regress today's read paths.

Every write updates the FHIR source-of-truth + an audit row (opaque ids only) and
publishes a cache-invalidation so the change takes effect within a round-trip, not
a TTL (03 §5.2). Patients may only change their own consent (self-check on the
``phn`` claim).
"""

from __future__ import annotations

import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
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
CONSENT_SCOPE_SYSTEM = "http://terminology.hl7.org/CodeSystem/consentscope"

FACE_CATEGORY = "face-recognition"          # biometric check-in gate (never masks records)
RECORD_SHARING_CATEGORY = "record-sharing"  # governs FHIR record visibility, per purpose

# Per-purpose record sharing. The key is our stable API id (used by the portal and
# the audit trail); the value is the FHIR PurposeOfUse (v3 ActReason) code stamped
# on the Consent's provision — the same code the request carries in X-MedAgent-Purpose
# and the ConsentInterceptor matches a deny against.
PURPOSE_SYSTEM = "http://terminology.hl7.org/CodeSystem/v3-ActReason"
PURPOSES: dict[str, str] = {
    "treatment": "TREAT",
    "research": "HRESCH",
    "marketing": "HMARKT",
}
_CODE_TO_PURPOSE: dict[str, str] = {code: key for key, code in PURPOSES.items()}


class ConsentState(BaseModel):
    """Full consent state for a patient: the biometric gate plus each record-sharing
    purpose (True = allowed / ``permit``, False = denied / ``deny``)."""

    face_recognition: bool
    purposes: dict[str, bool]


class ConsentUpdate(BaseModel):
    """A single consent change. Exactly one surface is set per request:

    * ``{"face_recognition": bool}`` — the biometric check-in gate (back-compat).
    * ``{"purpose": "treatment|research|marketing", "granted": bool}`` — one
      record-sharing purpose, set independently of the others.
    """

    face_recognition: bool | None = None
    purpose: str | None = None
    granted: bool | None = None


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


async def _patient_fhir_id(fhir: FHIRClient, phn: str) -> str | None:
    matches = await fhir.search("Patient", {"identifier": f"{PHN_SYSTEM}|{phn}"})
    return matches[0]["id"] if matches else None


def _default_purpose_states() -> dict[str, bool]:
    """Fail-safe / default state: every purpose ALLOWED (nothing is masked)."""
    return {key: True for key in PURPOSES}


def _purpose_states_from(consents: list[dict[str, Any]]) -> dict[str, bool]:
    """Reduce a patient's active Consents to the current allow/deny per purpose.

    Newest provision wins (consents are versioned by append, so the latest write
    for a purpose is its current state). A purpose with no consent stays ALLOWED.
    """
    states = _default_purpose_states()
    ordered = sorted(
        consents,
        key=lambda c: str((c.get("meta") or {}).get("lastUpdated", "")),
        reverse=True,
    )
    settled: set[str] = set()
    for consent in ordered:
        if str(consent.get("status")) != "active":
            continue
        provision = consent.get("provision") or {}
        permit = provision.get("type") == "permit"
        for coding in provision.get("purpose") or []:
            key = _CODE_TO_PURPOSE.get(coding.get("code"))
            if key and key not in settled:
                states[key] = permit
                settled.add(key)
    return states


async def _read_purpose_states(fhir: FHIRClient, pid: str | None) -> dict[str, bool]:
    """Latest per-purpose allow/deny for a patient. Fail-safe: on any read error, or
    a patient with no FHIR record, default to ALLOW so the portal never masks or 500s."""
    if pid is None:
        return _default_purpose_states()
    try:
        consents = await fhir.search(
            "Consent", {"patient": f"Patient/{pid}", "status": "active", "_count": "200"}
        )
    except Exception:  # pragma: no cover - defensive; consent read must not break the portal
        logger.warning("consent: per-purpose read failed; defaulting to allow", exc_info=True)
        return _default_purpose_states()
    return _purpose_states_from(consents)


def _consent_resource(pid: str, category: str, permit: bool, purpose_code: str | None) -> dict[str, Any]:
    resource: dict[str, Any] = {
        "resourceType": "Consent",
        "status": "active",
        "scope": {"coding": [{"system": CONSENT_SCOPE_SYSTEM, "code": "patient-privacy"}]},
        "category": [{"coding": [{"system": CONSENT_CATEGORY_SYSTEM, "code": category}]}],
        "patient": {"reference": f"Patient/{pid}"},
        "provision": {"type": "permit" if permit else "deny"},
    }
    if purpose_code is not None:
        # provision.purpose is what the ConsentInterceptor matches a deny against —
        # a per-purpose deny masks only requests carrying that PurposeOfUse.
        resource["provision"]["purpose"] = [{"system": PURPOSE_SYSTEM, "code": purpose_code}]
    return resource


@router.get("/{phn}/consent", response_model=ConsentState)
async def get_consent(
    phn: str,
    principal: Annotated[Principal, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ConsentState:
    _self_guard(principal, phn)
    row = await _mpi_row(session, phn)
    fhir = FHIRClient(settings.fhir_base_url)
    try:
        pid = await _patient_fhir_id(fhir, phn)
        purposes = await _read_purpose_states(fhir, pid)
    finally:
        await fhir.close()
    return ConsentState(face_recognition=row.face_consent, purposes=purposes)


@router.put("/{phn}/consent", response_model=ConsentState)
async def set_consent(
    phn: str,
    body: ConsentUpdate,
    principal: Annotated[Principal, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> ConsentState:
    _self_guard(principal, phn)
    row = await _mpi_row(session, phn)

    # Per-purpose record-sharing change (new surface).
    if body.purpose is not None:
        purpose_key = body.purpose.lower()
        if purpose_key not in PURPOSES:
            raise HTTPException(status_code=422, detail="unknown consent purpose")
        if body.granted is None:
            raise HTTPException(status_code=422, detail="granted is required for a purpose change")
        return await _set_purpose(phn, purpose_key, body.granted, row, principal, session, settings, redis)

    # Biometric face-recognition change (back-compat surface).
    if body.face_recognition is not None:
        return await _set_face(phn, body.face_recognition, row, principal, session, settings, redis)

    raise HTTPException(status_code=422, detail="no consent change supplied")


async def _set_face(
    phn: str,
    granted: bool,
    row: PatientMPI,
    principal: Principal,
    session: AsyncSession,
    settings: Settings,
    redis: Redis,
) -> ConsentState:
    """Biometric check-in gate — unchanged behaviour: flip the MPI gate + write a
    versioned face-recognition Consent (which the interceptor never masks on)."""
    row.face_consent = granted

    fhir = FHIRClient(settings.fhir_base_url)
    try:
        pid = await _patient_fhir_id(fhir, phn)
        if pid is not None:
            await fhir.create("Consent", _consent_resource(pid, FACE_CATEGORY, granted, purpose_code=None))
        purposes = await _read_purpose_states(fhir, pid)
    finally:
        await fhir.close()

    session.add(AuditOutbox(event={
        "type": "consent_change",
        "actor": principal.subject,
        "patient_fhir_id": None,
        "category": FACE_CATEGORY,
        "granted": granted,
        "phn_last4": phn[-4:],
    }))
    await redis.publish("events:consent:invalidate", json.dumps({"phn": phn, "category": FACE_CATEGORY}))
    logger.info("consent updated", extra={"category": FACE_CATEGORY, "granted": granted})
    return ConsentState(face_recognition=granted, purposes=purposes)


async def _set_purpose(
    phn: str,
    purpose_key: str,
    granted: bool,
    row: PatientMPI,
    principal: Principal,
    session: AsyncSession,
    settings: Settings,
    redis: Redis,
) -> ConsentState:
    """Set ONE record-sharing purpose's allow/deny, independent of the others."""
    purpose_code = PURPOSES[purpose_key]

    fhir = FHIRClient(settings.fhir_base_url)
    try:
        pid = await _patient_fhir_id(fhir, phn)
        if pid is not None:
            await fhir.create("Consent", _consent_resource(pid, RECORD_SHARING_CATEGORY, granted, purpose_code))
        # Reflect the change immediately; overlay the just-set value in case the
        # store's search index lags the write we just made.
        purposes = await _read_purpose_states(fhir, pid)
        purposes[purpose_key] = granted
    finally:
        await fhir.close()

    session.add(AuditOutbox(event={
        "type": "consent_change",
        "actor": principal.subject,
        "patient_fhir_id": None,
        "category": RECORD_SHARING_CATEGORY,
        "purpose": purpose_key,
        "purpose_code": purpose_code,
        "granted": granted,
        "phn_last4": phn[-4:],
    }))
    await redis.publish(
        "events:consent:invalidate",
        json.dumps({"phn": phn, "category": RECORD_SHARING_CATEGORY, "purpose": purpose_key}),
    )
    logger.info("consent updated", extra={"category": RECORD_SHARING_CATEGORY, "purpose": purpose_key, "granted": granted})
    return ConsentState(face_recognition=row.face_consent, purposes=purposes)

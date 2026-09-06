"""National-integration endpoints (FACADES) — 09-integrations-national.md §2/§3/§5.

Thin HTTP surface over the adapter clients in app/integrations/*. One representative
write endpoint per integration, plus a health endpoint that reports which integrations
are enabled/configured. Every integration is OFF by default (config.py): a disabled or
unconfigured integration returns a clear 503 "not enabled" payload — never a 500 — and
nothing here can block care (spec §5.3/§6.2 invariants).

These are HONEST facades: the same adapters point at the local simulator
(services/national-sim) today and at the real NDHX / SLUDI / HHIMS endpoints when
configured. No endpoint here fabricates a national record.

Writes are audited via the outbox, exactly like the other write-back routers
(lab_order.py / referrals.py). Payloads carry opaque ids only — no UIN, no PHI beyond
the PHN the clinician already holds.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import Principal, require_roles, require_user
from app.config import Settings
from app.deps import get_session, get_settings
from app.integrations import IntegrationResult
from app.integrations.hhims import HhimsClient
from app.integrations.ndhx import NdhxClient
from app.integrations.sludi import SludiClient
from app.models import AuditOutbox

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations", tags=["integrations-national"])

# HTTP status for a call that did not succeed at the adapter boundary.
_DISABLED_HTTP = status.HTTP_503_SERVICE_UNAVAILABLE  # enabled=false or unconfigured
_UPSTREAM_HTTP = status.HTTP_502_BAD_GATEWAY  # reached the upstream, it failed


def _http_status(result: IntegrationResult) -> int:
    if result.ok:
        return status.HTTP_200_OK
    if result.is_disabled:
        return _DISABLED_HTTP
    return _UPSTREAM_HTTP


def _respond(result: IntegrationResult) -> JSONResponse:
    return JSONResponse(status_code=_http_status(result), content=result.as_dict())


async def _audit_write(
    session: AsyncSession, principal: Principal, result: IntegrationResult, action: str
) -> None:
    """Audit a national-exchange write attempt (opaque ids only — no PHI/UIN)."""
    session.add(
        AuditOutbox(
            event={
                "type": action,
                "actor": principal.subject,
                "integration": result.integration,
                "outcome": result.status,
                "upstream_status": result.status_code,
            }
        )
    )


# --------------------------------------------------------------------------- health


@router.get("/health")
async def integrations_health(
    principal: Annotated[Principal, Depends(require_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """Which national integrations are enabled/configured (no secrets). Reflects the
    facade posture: `available` is true only when a flag is ON and a base URL is set."""
    clients = {
        "ndhx": NdhxClient.from_settings(settings),
        "sludi": SludiClient.from_settings(settings),
        "hhims": HhimsClient.from_settings(settings),
    }
    integrations = {name: client.status() for name, client in clients.items()}
    return {
        "note": "facades over the §09 national-integration spec; live when pointed at "
        "real NDHX/SLUDI/HHIMS endpoints, else the local simulator or disabled",
        "any_available": any(v["available"] for v in integrations.values()),
        "integrations": integrations,
    }


# --------------------------------------------------------------------------- NDHX


class NdhxShareRequest(BaseModel):
    patient_phn: str = Field(min_length=1, description="Patient PHN (Patient.identifier)")
    summary: str = Field(min_length=1, description="Clinical summary text to share")
    type_display: str = Field("Discharge summary", description="Document type label")


@router.post("/ndhx/share", dependencies=[require_roles("doctor", "nurse", "admin")])
async def ndhx_share(
    body: NdhxShareRequest,
    principal: Annotated[Principal, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> JSONResponse:
    """Share a clinical summary to the national exchange (NDHX) as a FHIR
    DocumentReference (§2.2). 503 if NDHX is not enabled/configured."""
    client = NdhxClient.from_settings(settings)
    result = await client.push_document(
        patient_phn=body.patient_phn,
        summary_text=body.summary,
        type_display=body.type_display,
        author_display=principal.subject,
    )
    await _audit_write(session, principal, result, "ndhx_document_shared")
    logger.info("ndhx share", extra={"outcome": result.status, "phn": body.patient_phn})
    return _respond(result)


@router.get("/ndhx/locator")
async def ndhx_locator(
    phn: str,
    principal: Annotated[Principal, Depends(require_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> JSONResponse:
    """Fetch a patient's national record locator from NDHX via an MPI Patient search
    (§2.1). Read-only, so no audit-write. 503 if NDHX is not enabled/configured."""
    client = NdhxClient.from_settings(settings)
    result = await client.fetch_locator(phn)
    return _respond(result)


# --------------------------------------------------------------------------- SLUDI


class SludiVerifyRequest(BaseModel):
    vid_token: str = Field(min_length=1, description="SLUDI virtual ID (VID) / token")
    otp: str | None = Field(default=None, description="OTP to the registered mobile")
    request_ekyc: bool = Field(default=False, description="Also request eKYC (if consented)")


@router.post("/sludi/verify", dependencies=[require_roles("receptionist", "admin", "doctor", "nurse")])
async def sludi_verify(
    body: SludiVerifyRequest,
    principal: Annotated[Principal, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> JSONResponse:
    """Verify a national digital identity via SLUDI (MOSIP IDA) — VID(+OTP) exchanged for
    a yes/no result and a partner-specific token (§5.1). We persist only the partner
    token, NEVER the UIN (ADR I-7). 503 if SLUDI is not enabled/configured."""
    client = SludiClient.from_settings(settings)
    result = await client.verify_identity(
        body.vid_token, otp=body.otp, request_ekyc=body.request_ekyc
    )
    await _audit_write(session, principal, result, "sludi_identity_verified")
    logger.info("sludi verify", extra={"outcome": result.status})
    return _respond(result)


# --------------------------------------------------------------------------- HHIMS


class HhimsEncounterRequest(BaseModel):
    patient_phn: str = Field(min_length=1, description="Patient PHN (Patient.identifier)")
    summary: str = Field(min_length=1, description="Encounter / discharge summary text")
    reason: str | None = Field(default=None, description="Reason for the encounter")


@router.post("/hhims/encounter", dependencies=[require_roles("doctor", "nurse", "admin")])
async def hhims_encounter(
    body: HhimsEncounterRequest,
    principal: Annotated[Principal, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> JSONResponse:
    """Exchange an encounter / discharge summary with a hospital HIS via the HHIMS FHIR
    facade (§3.1 B2). Goes through the connector's interface, never a DB write (ADR I-2).
    503 if HHIMS is not enabled/configured."""
    client = HhimsClient.from_settings(settings)
    result = await client.send_encounter(
        patient_phn=body.patient_phn, summary_text=body.summary, reason_text=body.reason
    )
    await _audit_write(session, principal, result, "hhims_encounter_sent")
    logger.info("hhims encounter", extra={"outcome": result.status, "phn": body.patient_phn})
    return _respond(result)

"""Audit endpoints (03 §5.3): manual outbox flush (internal/ops) and the patient
access log (FR-5.8) / admin recent-events view (FR-6.3), read from FHIR AuditEvent.
"""

from __future__ import annotations

from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.audit import dispatch_once
from app.auth import Principal, require_user
from app.config import Settings
from app.deps import get_settings
from app.fhir_client import FHIRClient

PHN_SYSTEM = "https://fhir.medagent.health.lk/id/phn"

internal_router = APIRouter(prefix="/internal/audit", tags=["audit-internal"])
public_router = APIRouter(prefix="/audit", tags=["audit"])


@internal_router.post("/dispatch")
async def flush(request: Request) -> dict[str, int]:
    """Drain the audit outbox now (ops/tests). The lifespan loop does this on an interval."""
    settings: Settings = request.app.state.settings
    sm: async_sessionmaker = request.app.state.sessionmaker
    n = await dispatch_once(sm, settings.fhir_base_url)
    return {"dispatched": n}


@public_router.get("/access-log")
async def access_log(
    principal: Annotated[Principal, Depends(require_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    patient: Annotated[str, Query(min_length=1, description="Patient PHN or FHIR id")],
) -> list[dict[str, Any]]:
    """Human-readable access log for a patient (FR-5.8) — AuditEvents referencing them."""
    fhir = FHIRClient(settings.fhir_base_url)
    try:
        pid = patient
        if patient.isdigit():
            rows = await fhir.search("Patient", {"identifier": f"{PHN_SYSTEM}|{patient}"})
            if rows:
                pid = str(rows[0]["id"])
        events = await fhir.search("AuditEvent", {"entity": f"Patient/{pid}", "_sort": "-date"})
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="audit store unavailable") from exc
    finally:
        await fhir.close()

    out: list[dict[str, Any]] = []
    for e in events:
        agent = (e.get("agent") or [{}])[0].get("who", {}).get("display", "unknown")
        out.append({
            "recorded": e.get("recorded"),
            "action": e.get("action"),
            "type": (e.get("type") or {}).get("code"),
            "by": agent,
            "outcome_desc": e.get("outcomeDesc"),
        })
    return out

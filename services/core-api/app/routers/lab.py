"""National lab network — LIS hub (FR-8, 03 §3.5). Phase-2 backlog 2.1.

A lab order is a `ServiceRequest` (created via the write-back path). This module
tracks each order's specimen through the operational lifecycle the spec defines:

    ordered → collected → in-transit → received → in-progress → resulted → released

The state is stored as an extension on the ServiceRequest itself (read by id — no
dependency on a search index), so a transition is a read-modify-write of the
order. Every transition is audited via the outbox. Barcode/accession (2.2),
analyzer interface (2.3) and result release (2.4) build on this state machine.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import Principal, require_user
from app.config import Settings
from app.deps import get_session, get_settings
from app.fhir_client import FHIRClient
from app.models import AuditOutbox

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/lab", tags=["lab"])

PHN_SYSTEM = "https://fhir.medagent.health.lk/id/phn"
LAB_CATEGORY_CODE = "108252007"  # SNOMED "Laboratory procedure" (set by write-back)
LAB_STATE_EXT = "https://fhir.medagent.health.lk/ext/lab-state"

# The specimen lifecycle. Linear: an order advances one step at a time.
STATES = ["ordered", "collected", "in-transit", "received", "in-progress", "resulted", "released"]


def _bearer(request: Request) -> str | None:
    h = request.headers.get("authorization", "")
    return h[7:] if h.lower().startswith("bearer ") else None


def _cc_text(cc: dict[str, Any] | None) -> str:
    if not cc:
        return ""
    if cc.get("text"):
        return cc["text"]
    for c in cc.get("coding", []):
        return c.get("display") or c.get("code") or ""
    return ""


def _is_lab(sr: dict[str, Any]) -> bool:
    return any(
        c.get("code") == LAB_CATEGORY_CODE
        for cat in sr.get("category", [])
        for c in cat.get("coding", [])
    )


def _state_of(sr: dict[str, Any]) -> str:
    for ext in sr.get("extension", []):
        if ext.get("url") == LAB_STATE_EXT:
            return ext.get("valueString", "ordered")
    return "ordered"


def _with_state(sr: dict[str, Any], state: str) -> dict[str, Any]:
    exts = [e for e in sr.get("extension", []) if e.get("url") != LAB_STATE_EXT]
    exts.append({"url": LAB_STATE_EXT, "valueString": state})
    return {**sr, "extension": exts}


async def _resolve_patient(fhir: FHIRClient, ref: str) -> str | None:
    if ref.isdigit():
        rows = await fhir.search("Patient", {"identifier": f"{PHN_SYSTEM}|{ref}"})
        if rows:
            return str(rows[0]["id"])
    try:
        return str((await fhir.read("Patient", ref))["id"])
    except Exception:  # noqa: BLE001
        return None


class LabOrderState(BaseModel):
    id: str
    test: str
    state: str
    priority: str | None = None


@router.get("/worklist", response_model=list[LabOrderState])
async def worklist(
    patient: str,
    principal: Annotated[Principal, Depends(require_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> list[LabOrderState]:
    """A patient's lab orders with their current specimen state (FR-8.7)."""
    fhir = FHIRClient(settings.fhir_base_url)
    try:
        pid = await _resolve_patient(fhir, patient)
        if not pid:
            raise HTTPException(status_code=404, detail=f"no FHIR patient for {patient}")
        srs = await fhir.search("ServiceRequest", {"patient": pid})
        return [
            LabOrderState(id=str(sr["id"]), test=_cc_text(sr.get("code")),
                          state=_state_of(sr), priority=sr.get("priority"))
            for sr in srs if _is_lab(sr)
        ]
    finally:
        await fhir.close()


class AdvanceRequest(BaseModel):
    to: str | None = None  # optional explicit target; default = next state


@router.post("/{service_request_id}/advance", response_model=LabOrderState)
async def advance(
    service_request_id: str,
    body: AdvanceRequest,
    request: Request,
    principal: Annotated[Principal, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> LabOrderState:
    """Advance a lab order's specimen to the next state (or an explicit `to`),
    enforcing the transition matrix; audits every move (FR-8.7)."""
    token = _bearer(request)
    fhir = FHIRClient(settings.fhir_base_url)
    try:
        try:
            sr = await fhir.read("ServiceRequest", service_request_id)
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=404, detail="lab order not found")
        if not _is_lab(sr):
            raise HTTPException(status_code=422, detail="not a laboratory order")
        pid = str(sr.get("subject", {}).get("reference", "")).split("/")[-1]

        current = _state_of(sr)
        cur_idx = STATES.index(current)
        if body.to is not None:
            if body.to not in STATES:
                raise HTTPException(status_code=422, detail=f"unknown state '{body.to}'")
            if STATES.index(body.to) != cur_idx + 1:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                    detail=f"invalid transition {current} -> {body.to} (advance one step)")
            nxt = body.to
        else:
            if cur_idx + 1 >= len(STATES):
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"order already {current}")
            nxt = STATES[cur_idx + 1]

        # Mark the order completed on the FHIR resource once released.
        updated = _with_state(sr, nxt)
        if nxt == "released":
            updated["status"] = "completed"
        await fhir.update("ServiceRequest", service_request_id, updated, token)

        session.add(AuditOutbox(event={
            "type": "lab_state_change",
            "actor": principal.subject,
            "patient_fhir_id": pid,
            "committed": f"ServiceRequest/{service_request_id}",
            "from_state": current,
            "to_state": nxt,
        }))
        logger.info("lab state change", extra={"order": service_request_id, "to": nxt})
        return LabOrderState(id=service_request_id, test=_cc_text(sr.get("code")),
                             state=nxt, priority=sr.get("priority"))
    finally:
        await fhir.close()

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
import uuid
from typing import Annotated, Any

import barcode
from barcode.writer import SVGWriter
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
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
ACCESSION_SYSTEM = "https://fhir.medagent.health.lk/id/lab-accession"


def _new_accession() -> str:
    """Human-scannable, unique accession id (FR-8.2). Barcode-friendly (A–Z0–9)."""
    return "MA" + uuid.uuid4().hex[:10].upper()


def _accession_of(sr: dict[str, Any]) -> str | None:
    for ident in sr.get("identifier", []):
        if ident.get("system") == ACCESSION_SYSTEM:
            return ident.get("value")
    return None


def _barcode_svg(value: str) -> bytes:
    """Render a Code 128 barcode as SVG for printing (FR-8.2)."""
    return barcode.get("code128", value, writer=SVGWriter()).render()

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
    accession: str | None = None


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
                          state=_state_of(sr), priority=sr.get("priority"),
                          accession=_accession_of(sr))
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

        updated = _with_state(sr, nxt)
        if nxt == "released":
            updated["status"] = "completed"

        # On collection: assign an accession (FR-8.2) + create the Specimen, so a
        # barcode label can be printed and analyzers can reference it (2.3).
        accession = _accession_of(sr)
        if nxt == "collected" and not accession:
            accession = _new_accession()
            updated.setdefault("identifier", []).append(
                {"system": ACCESSION_SYSTEM, "value": accession}
            )
            await fhir.create("Specimen", {
                "resourceType": "Specimen",
                "status": "available",
                "accessionIdentifier": {"system": ACCESSION_SYSTEM, "value": accession},
                "subject": {"reference": f"Patient/{pid}"},
                "request": [{"reference": f"ServiceRequest/{service_request_id}"}],
            }, token)

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
                             state=nxt, priority=sr.get("priority"), accession=accession)
    finally:
        await fhir.close()


@router.get("/{service_request_id}/label")
async def label(
    service_request_id: str,
    principal: Annotated[Principal, Depends(require_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    """Printable specimen barcode label (Code 128 of the accession, FR-8.2).
    Returns SVG so it prints crisply at any size."""
    fhir = FHIRClient(settings.fhir_base_url)
    try:
        try:
            sr = await fhir.read("ServiceRequest", service_request_id)
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=404, detail="lab order not found")
        accession = _accession_of(sr)
        if not accession:
            raise HTTPException(status_code=409, detail="no accession yet — collect the specimen first")
        return Response(content=_barcode_svg(accession), media_type="image/svg+xml")
    finally:
        await fhir.close()


# --- Analyzer interface (FR-8.3, backlog 2.3) --------------------------------
# Bidirectional interface: the analyzer scans the barcode, PULLs the order, runs,
# and PUSHes the result. Modelled here as JSON keyed by the accession; a real
# deployment wraps these in an ASTM E1394 / HL7 v2 (ORU) framing adapter.

async def _find_by_accession(fhir: FHIRClient, accession: str) -> dict[str, Any] | None:
    rows = await fhir.search("ServiceRequest", {"identifier": f"{ACCESSION_SYSTEM}|{accession}"})
    return rows[0] if rows else None


async def _audit_lab(session: AsyncSession, actor: str, pid: str, sr_id: str, frm: str, to: str) -> None:
    session.add(AuditOutbox(event={
        "type": "lab_state_change", "actor": actor, "patient_fhir_id": pid,
        "committed": f"ServiceRequest/{sr_id}", "from_state": frm, "to_state": to,
    }))


@router.post("/analyzer/pull")
async def analyzer_pull(
    accession: str,
    request: Request,
    principal: Annotated[Principal, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """Analyzer scans the barcode and pulls the order. Requires the specimen to be
    received at the lab; moves it to in-progress and returns what to run."""
    token = _bearer(request)
    fhir = FHIRClient(settings.fhir_base_url)
    try:
        sr = await _find_by_accession(fhir, accession)
        if not sr or not _is_lab(sr):
            raise HTTPException(status_code=404, detail="no lab order for that accession")
        sr_id = str(sr["id"])
        pid = str(sr.get("subject", {}).get("reference", "")).split("/")[-1]
        current = _state_of(sr)
        if current != "received":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail=f"specimen is '{current}', must be 'received' to pull")
        await fhir.update("ServiceRequest", sr_id, _with_state(sr, "in-progress"), token)
        await _audit_lab(session, principal.subject, pid, sr_id, current, "in-progress")
        loinc = next((c.get("code") for c in (sr.get("code") or {}).get("coding", [])
                      if c.get("system") == "http://loinc.org"), None)
        return {"accession": accession, "order_id": sr_id, "test": _cc_text(sr.get("code")),
                "loinc": loinc, "patient": pid, "state": "in-progress"}
    finally:
        await fhir.close()


class AnalyzerResult(BaseModel):
    accession: str
    value: float
    unit: str | None = ""
    loinc: str | None = None
    test: str | None = None


@router.post("/analyzer/result")
async def analyzer_result(
    body: AnalyzerResult,
    request: Request,
    principal: Annotated[Principal, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """Analyzer pushes a result back. Stores a preliminary Observation linked to
    the order and moves the specimen to resulted (release/validation is 2.4)."""
    token = _bearer(request)
    fhir = FHIRClient(settings.fhir_base_url)
    try:
        sr = await _find_by_accession(fhir, body.accession)
        if not sr or not _is_lab(sr):
            raise HTTPException(status_code=404, detail="no lab order for that accession")
        sr_id = str(sr["id"])
        pid = str(sr.get("subject", {}).get("reference", "")).split("/")[-1]
        current = _state_of(sr)
        if current != "in-progress":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail=f"specimen is '{current}', must be 'in-progress' to accept a result")
        code: dict[str, Any] = {"text": body.test or _cc_text(sr.get("code"))}
        if body.loinc:
            code["coding"] = [{"system": "http://loinc.org", "code": body.loinc}]
        obs = await fhir.create("Observation", {
            "resourceType": "Observation",
            "status": "preliminary",  # released/validated in 2.4
            "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category",
                                      "code": "laboratory"}]}],
            "code": code,
            "subject": {"reference": f"Patient/{pid}"},
            "basedOn": [{"reference": f"ServiceRequest/{sr_id}"}],
            "valueQuantity": {"value": body.value, "unit": body.unit or "",
                              "system": "http://unitsofmeasure.org", "code": body.unit or ""},
        }, token)
        await fhir.update("ServiceRequest", sr_id, _with_state(sr, "resulted"), token)
        await _audit_lab(session, principal.subject, pid, sr_id, current, "resulted")
        return {"accession": body.accession, "order_id": sr_id,
                "result": f"Observation/{obs.get('id')}", "state": "resulted"}
    finally:
        await fhir.close()

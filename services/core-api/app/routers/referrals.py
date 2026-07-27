"""Referral network (FR-9, 03 §3.6). Phase-2 backlog 5.1.

A referral routes a patient from one clinician/facility to a specialist or
receiving facility. It is modelled as a FHIR pair:

  * `ServiceRequest` (intent=order, category = SNOMED 3457005 "Patient referral")
    — the clinical request itself (specialty, reason, priority).
  * `Task` (intent=order, focus → the ServiceRequest, `for` → the Patient) — the
    workflow token the receiving side acts on. Its native `status` carries the
    lifecycle:

        requested → accepted → in-progress → completed
        requested → rejected          (declined by the receiver)

The destination facility is stamped as a `meta.tag` so the receiving inbox is a
single indexed `_tag` search — no Organization resources required for the pilot.
Every state change is audited via the outbox.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import Principal, require_user
from app.config import Settings
from app.deps import get_session, get_settings
from app.fhir_client import FHIRClient
from app.models import AuditOutbox

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/referrals", tags=["referrals"])

PHN_SYSTEM = "https://fhir.medagent.health.lk/id/phn"
REFERRAL_CATEGORY_CODE = "3457005"  # SNOMED "Patient referral"
REFERRAL_FACILITY_SYSTEM = "https://fhir.medagent.health.lk/cs/referral-facility"

# Native FHIR Task.status values we use, and the transitions the receiver may make.
_TRANSITIONS: dict[str, str] = {
    "accept": "accepted",
    "reject": "rejected",
    "start": "in-progress",
    "complete": "completed",
}
# Which current statuses each action is allowed from.
_ALLOWED_FROM: dict[str, set[str]] = {
    "accepted": {"requested"},
    "rejected": {"requested", "accepted"},
    "in-progress": {"accepted"},
    "completed": {"accepted", "in-progress"},
}
_ACTIVE = {"requested", "accepted", "in-progress"}


def can_transition(current: str | None, action: str) -> bool:
    """Whether a referral in `current` status may take `action` (pure, testable)."""
    target = _TRANSITIONS.get(action)
    return target is not None and current in _ALLOWED_FROM.get(target, set())


async def _resolve_pid(fhir: FHIRClient, phn: str) -> dict[str, Any] | None:
    if not phn.isdigit():
        return await _safe_read(fhir, phn)
    rows = await fhir.search("Patient", {"identifier": f"{PHN_SYSTEM}|{phn}"})
    return rows[0] if rows else None


async def _safe_read(fhir: FHIRClient, pid: str) -> dict[str, Any] | None:
    try:
        return await fhir.read("Patient", pid)
    except Exception:  # noqa: BLE001
        return None


def _facility_tag(task: dict[str, Any]) -> str | None:
    for tag in (task.get("meta") or {}).get("tag", []):
        if tag.get("system") == REFERRAL_FACILITY_SYSTEM:
            return tag.get("code")
    return None


def _patient_name(patient: dict[str, Any]) -> str:
    name = next((n for n in patient.get("name", [])), {})
    return name.get("text") or " ".join(name.get("given", []) + [name.get("family", "")]).strip() or "Unknown"


def _view(task: dict[str, Any], patient_name: str | None = None) -> dict[str, Any]:
    return {
        "task_id": task.get("id"),
        "referral_ref": (task.get("focus") or {}).get("reference"),
        "patient_ref": (task.get("for") or {}).get("reference"),
        "patient_name": patient_name,
        "to_facility": _facility_tag(task),
        "specialty": (task.get("code") or {}).get("text"),
        "reason": next((r.get("text") for r in task.get("reasonCode", []) if isinstance(r, dict)), None)
        if isinstance(task.get("reasonCode"), list) else (task.get("reasonCode") or {}).get("text"),
        "priority": task.get("priority"),
        "status": task.get("status"),
        "requested_by": (task.get("requester") or {}).get("display"),
        "authored_on": task.get("authoredOn"),
    }


class ReferralRequest(BaseModel):
    patient: str = Field(..., description="Patient PHN or FHIR id")
    to_facility: str = Field(..., min_length=1, description="Destination facility id")
    specialty: str = Field(..., min_length=1, description="Requested specialty / clinic")
    reason: str = Field(..., min_length=1)
    priority: str = Field("routine", pattern="^(routine|urgent|asap|stat)$")
    note: str | None = None


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_referral(
    body: ReferralRequest,
    request: Request,
    principal: Annotated[Principal, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """Create a referral to another facility/specialist (FR-9.1): a ServiceRequest
    plus a Task the receiving inbox acts on."""
    auth = request.headers.get("authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else None
    fhir = FHIRClient(settings.fhir_base_url)
    try:
        patient = await _resolve_pid(fhir, body.patient)
        if not patient:
            raise HTTPException(status_code=404, detail=f"no FHIR patient for {body.patient}")
        pid = str(patient["id"])
        now = datetime.now(timezone.utc).isoformat()

        sr = await fhir.create("ServiceRequest", {
            "resourceType": "ServiceRequest", "status": "active", "intent": "order",
            "priority": body.priority,
            "category": [{"coding": [{"system": "http://snomed.info/sct",
                                      "code": REFERRAL_CATEGORY_CODE, "display": "Patient referral"}]}],
            "code": {"text": body.specialty},
            "subject": {"reference": f"Patient/{pid}"},
            "authoredOn": now,
            "reasonCode": [{"text": body.reason}],
            "note": ([{"text": body.note}] if body.note else []),
        }, token)
        sr_id = str(sr["id"])

        task = await fhir.create("Task", {
            "resourceType": "Task", "status": "requested", "intent": "order",
            "priority": body.priority,
            "meta": {"tag": [{"system": REFERRAL_FACILITY_SYSTEM, "code": body.to_facility}]},
            "code": {"text": body.specialty},
            "focus": {"reference": f"ServiceRequest/{sr_id}"},
            "for": {"reference": f"Patient/{pid}"},
            "authoredOn": now,
            "requester": {"display": principal.subject},
            "reasonCode": {"text": body.reason},
        }, token)
        task_id = str(task["id"])

        session.add(AuditOutbox(event={
            "type": "referral_created", "actor": principal.subject, "patient_fhir_id": pid,
            "committed": f"Task/{task_id}", "to_facility": body.to_facility, "specialty": body.specialty,
        }))
        return {"task_id": task_id, "referral_ref": f"ServiceRequest/{sr_id}",
                "status": "requested", "to_facility": body.to_facility}
    finally:
        await fhir.close()


@router.get("/inbox")
async def inbox(
    principal: Annotated[Principal, Depends(require_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    facility: Annotated[str, Query(min_length=1, description="Receiving facility id")],
    include_closed: bool = False,
) -> dict[str, Any]:
    """Inbound referral worklist for a receiving facility (FR-9.2). Active items
    (requested/accepted/in-progress) unless include_closed=true."""
    fhir = FHIRClient(settings.fhir_base_url)
    try:
        tasks = await fhir.search("Task", {"_tag": f"{REFERRAL_FACILITY_SYSTEM}|{facility}",
                                           "_sort": "-authored-on", "_count": "100"})
        out = []
        for t in tasks:
            if not include_closed and t.get("status") not in _ACTIVE:
                continue
            pname = None
            ref = (t.get("for") or {}).get("reference", "")
            if ref.startswith("Patient/"):
                p = await _safe_read(fhir, ref.split("/", 1)[1])
                pname = _patient_name(p) if p else None
            out.append(_view(t, pname))
        return {"facility": facility, "count": len(out), "items": out}
    finally:
        await fhir.close()


@router.get("/outbox")
async def outbox(
    principal: Annotated[Principal, Depends(require_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    patient: Annotated[str, Query(min_length=1, description="Patient PHN or FHIR id")],
) -> dict[str, Any]:
    """Referrals raised for a patient (FR-9.4) with their current status — the
    'sent' view for the referring clinician and the patient portal."""
    fhir = FHIRClient(settings.fhir_base_url)
    try:
        p = await _resolve_pid(fhir, patient)
        if not p:
            raise HTTPException(status_code=404, detail=f"no FHIR patient for {patient}")
        pid = str(p["id"])
        tasks = await fhir.search("Task", {"patient": pid, "_sort": "-authored-on", "_count": "100"})
        items = [_view(t, _patient_name(p)) for t in tasks if _facility_tag(t)]
        return {"patient": f"Patient/{pid}", "count": len(items), "items": items}
    finally:
        await fhir.close()


class ReferralAction(BaseModel):
    action: str = Field(..., pattern="^(accept|reject|start|complete)$")
    note: str | None = None


@router.post("/{task_id}/act")
async def act_on_referral(
    task_id: str,
    body: ReferralAction,
    request: Request,
    principal: Annotated[Principal, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """Receiving-side transition on a referral (FR-9.3): accept / reject / start /
    complete. Validates the transition against the current status and audits it."""
    auth = request.headers.get("authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else None
    target = _TRANSITIONS[body.action]
    fhir = FHIRClient(settings.fhir_base_url)
    try:
        try:
            task = await fhir.read("Task", task_id)
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=404, detail="referral not found")
        current = task.get("status")
        if not can_transition(current, body.action):
            raise HTTPException(status_code=409,
                                detail=f"cannot {body.action} a referral in state '{current}'")
        task["status"] = target
        if body.note:
            task.setdefault("note", []).append({"text": body.note})
        await fhir.update("Task", task_id, task, token)

        ref = (task.get("for") or {}).get("reference", "")
        pid = ref.split("/", 1)[1] if ref.startswith("Patient/") else None
        session.add(AuditOutbox(event={
            "type": "referral_state_change", "actor": principal.subject, "patient_fhir_id": pid,
            "committed": f"Task/{task_id}", "from_state": current, "to_state": target,
        }))
        return {"task_id": task_id, "status": target, "from": current}
    finally:
        await fhir.close()

"""Disease registries & notifiable-disease surveillance (FR-11, 03 §3.8). Backlog 6.2.

When a diagnosis is a notifiable disease (Sri Lanka's list — dengue, malaria, TB,
measles, leptospirosis, cholera, rabies, …), this module:

  * records the case in a registry (a FHIR `Flag` on the patient, tagged with the
    disease + `notifiable` so line-listing and aggregation are one `_tag` search);
  * for an *immediately-notifiable* disease, raises a surveillance alert as a `Task`
    routed to the epidemiology unit's worklist (reusing the 5.1 inbox machinery);
  * exposes a DHIS2-ready aggregate feed (dataValueSet-shaped) for the national feed.

Deterministic-first: the notifiable list is a curated ruleset keyed by ICD-10 (with
a text fallback) — never a model decision.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import Principal, require_user
from app.config import Settings
from app.deps import get_session, get_settings
from app.fhir_client import FHIRClient
from app.fhir.helpers import PHN_SYSTEM, resolve_pid as _resolve_pid
from app.models import AuditOutbox
from app.routers.referrals import REFERRAL_FACILITY_SYSTEM

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/registry", tags=["registry"])

DISEASE_TAG = "https://fhir.medagent.health.lk/cs/notifiable-disease"
REGISTRY_TAG = "https://fhir.medagent.health.lk/cs/registry"
EPI_UNIT = "moh-epi-unit"  # surveillance inbox (via the referral Task machinery)

# Curated Sri Lanka notifiable-disease ruleset: ICD-10 3-char prefix ->
# (key, label, immediately_notifiable). `immediately_notifiable` raises an alert.
_ICD_NOTIFIABLE: dict[str, tuple[str, str, bool]] = {
    "A90": ("dengue", "Dengue fever", True), "A91": ("dengue", "Dengue haemorrhagic fever", True),
    "A97": ("dengue", "Dengue", True),
    "B50": ("malaria", "Malaria", True), "B51": ("malaria", "Malaria", True),
    "B52": ("malaria", "Malaria", True), "B53": ("malaria", "Malaria", True),
    "B54": ("malaria", "Malaria", True),
    "A15": ("tb", "Tuberculosis", False), "A16": ("tb", "Tuberculosis", False),
    "A17": ("tb", "Tuberculosis", False), "A18": ("tb", "Tuberculosis", False),
    "A19": ("tb", "Tuberculosis", False),
    "B05": ("measles", "Measles", True), "A27": ("leptospirosis", "Leptospirosis", True),
    "A00": ("cholera", "Cholera", True), "A01": ("enteric_fever", "Enteric fever (typhoid)", False),
    "A82": ("rabies", "Rabies", True), "A36": ("diphtheria", "Diphtheria", True),
    "A33": ("tetanus", "Neonatal tetanus", True), "A35": ("tetanus", "Tetanus", True),
    "B01": ("chickenpox", "Chickenpox", False), "B15": ("hepatitis_a", "Viral hepatitis A", False),
    "B16": ("hepatitis_b", "Viral hepatitis B", False),
}
_TEXT_NOTIFIABLE: list[tuple[str, tuple[str, str, bool]]] = [
    ("dengue", ("dengue", "Dengue fever", True)), ("malaria", ("malaria", "Malaria", True)),
    ("tuberculosis", ("tb", "Tuberculosis", False)), ("measles", ("measles", "Measles", True)),
    ("leptospirosis", ("leptospirosis", "Leptospirosis", True)), ("cholera", ("cholera", "Cholera", True)),
    ("typhoid", ("enteric_fever", "Enteric fever (typhoid)", False)), ("rabies", ("rabies", "Rabies", True)),
    ("diphtheria", ("diphtheria", "Diphtheria", True)), ("tetanus", ("tetanus", "Tetanus", True)),
    ("chickenpox", ("chickenpox", "Chickenpox", False)), ("hepatitis", ("hepatitis", "Viral hepatitis", False)),
]


def classify_notifiable(icd10: str | None, text: str) -> tuple[str, str, bool] | None:
    """(key, label, immediately_notifiable) if notifiable, else None."""
    if icd10:
        hit = _ICD_NOTIFIABLE.get(icd10.strip().upper()[:3])
        if hit:
            return hit
    low = (text or "").lower()
    for kw, hit in _TEXT_NOTIFIABLE:
        if kw in low:
            return hit
    return None




class ReportRequest(BaseModel):
    patient: str = Field(..., description="PHN or FHIR id")
    text: str = Field(..., min_length=1, description="Diagnosis text")
    icd10: str | None = None
    onset: str | None = None
    facility: str | None = None  # reporting facility (for the feed's orgUnit)


@router.post("/report", status_code=status.HTTP_201_CREATED)
async def report_case(
    body: ReportRequest,
    request: Request,
    principal: Annotated[Principal, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """Evaluate a diagnosis; if notifiable, register the case and (if immediately
    notifiable) raise a surveillance alert (FR-11.1/11.2)."""
    hit = classify_notifiable(body.icd10, body.text)
    if not hit:
        return {"notifiable": False, "disease": None}
    key, label, immediate = hit
    auth = request.headers.get("authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else None
    facility = body.facility or "pilot-hospital-1"
    fhir = FHIRClient(settings.fhir_base_url)
    try:
        patient = await _resolve_pid(fhir, body.patient)
        if not patient:
            raise HTTPException(status_code=404, detail=f"no FHIR patient for {body.patient}")
        pid = str(patient["id"])
        now = datetime.now(timezone.utc).isoformat()

        flag = await fhir.create("Flag", {
            "resourceType": "Flag", "status": "active",
            "category": [{"coding": [{"system": REGISTRY_TAG, "code": "notifiable-disease"}]}],
            "code": {"text": label, "coding": [{"system": DISEASE_TAG, "code": key}]},
            "subject": {"reference": f"Patient/{pid}"},
            "period": {"start": body.onset or now},
            "meta": {"tag": [{"system": DISEASE_TAG, "code": key},
                             {"system": REGISTRY_TAG, "code": "notifiable"},
                             {"system": REFERRAL_FACILITY_SYSTEM, "code": facility}]},
        }, token)
        flag_id = str(flag["id"])

        session.add(AuditOutbox(event={
            "type": "notifiable_disease_reported", "actor": principal.subject, "patient_fhir_id": pid,
            "committed": f"Flag/{flag_id}", "disease": key, "facility": facility,
        }))

        alert = None
        if immediate:
            task = await fhir.create("Task", {
                "resourceType": "Task", "status": "requested", "intent": "order", "priority": "urgent",
                "meta": {"tag": [{"system": REFERRAL_FACILITY_SYSTEM, "code": EPI_UNIT},
                                 {"system": DISEASE_TAG, "code": key}]},
                "code": {"text": f"Notifiable: {label}"},
                "focus": {"reference": f"Flag/{flag_id}"}, "for": {"reference": f"Patient/{pid}"},
                "authoredOn": now, "requester": {"display": principal.subject},
                "reasonCode": {"text": f"Immediately-notifiable disease reported at {facility}"},
            }, token)
            alert = {"task_id": str(task["id"]), "routed_to": EPI_UNIT}
            session.add(AuditOutbox(event={
                "type": "notifiable_disease_alert", "actor": principal.subject, "patient_fhir_id": pid,
                "committed": f"Task/{task['id']}", "disease": key, "routed_to": EPI_UNIT,
            }))
        return {"notifiable": True, "disease": key, "label": label, "immediate": immediate,
                "registry_entry": f"Flag/{flag_id}", "alert": alert}
    finally:
        await fhir.close()


@router.get("/cases")
async def line_list(
    principal: Annotated[Principal, Depends(require_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    disease: Annotated[str, Query(min_length=1, description="Disease key, e.g. dengue")],
) -> dict[str, Any]:
    """Surveillance line-list for one disease (FR-11.3)."""
    fhir = FHIRClient(settings.fhir_base_url)
    try:
        flags = await fhir.search("Flag", {"_tag": f"{DISEASE_TAG}|{disease}", "_count": "500"})
        cases = [{"ref": f"Flag/{f.get('id')}", "patient": (f.get("subject") or {}).get("reference"),
                  "onset": (f.get("period") or {}).get("start"),
                  "label": (f.get("code") or {}).get("text")} for f in flags]
        return {"disease": disease, "count": len(cases), "cases": cases}
    finally:
        await fhir.close()


@router.get("/feed")
async def dhis2_feed(
    principal: Annotated[Principal, Depends(require_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """DHIS2-ready aggregate feed (FR-11.4): notifiable-disease case counts shaped
    as a dataValueSet the national HMIS integration can push."""
    fhir = FHIRClient(settings.fhir_base_url)
    try:
        flags = await fhir.search("Flag", {"_tag": f"{REGISTRY_TAG}|notifiable", "_count": "1000"})
        counts: Counter[str] = Counter()
        labels: dict[str, str] = {}
        for f in flags:
            key = next((c.get("code") for c in (f.get("code") or {}).get("coding", [])
                        if c.get("system") == DISEASE_TAG), None)
            if key:
                counts[key] += 1
                labels[key] = (f.get("code") or {}).get("text", key)
        now = datetime.now(timezone.utc)
        period = now.strftime("%Y%m%d")
        values = [{"dataElement": f"notifiable_{k}", "label": labels[k], "period": period,
                   "orgUnit": "LK-NATIONAL", "value": v} for k, v in sorted(counts.items())]
        return {"generated": now.isoformat(), "period": period,
                "total_cases": sum(counts.values()), "dataValues": values}
    finally:
        await fhir.close()

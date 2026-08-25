"""Imaging AI triage (FR-10, 03 §3.7). Phase-2 backlog 6.1.

An imaging order is a `ServiceRequest` (imaging category, from the write-back path).
This module attaches the study + report and triages it **deterministic-first**: an
AI model may propose structured findings, but the *triage flag* and any *routing*
are decided by a curated ruleset here — the model never sets urgency on its own
(same principle as the Rx-safety engine and the lab result classifier).

  attach report → classify (normal / abnormal / urgent) → if urgent, auto-raise a
  referral into the receiving specialty's inbox (reusing the 5.1 referral Task).

A low AI confidence forces `needs_review` regardless of the keyword match, so an
uncertain read always reaches a radiologist rather than being quietly cleared.
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
from app.fhir.helpers import PHN_SYSTEM, resolve_pid as _resolve_pid
from app.schemas.clinical import ImagingReports
from app.models import AuditOutbox
from app.routers.referrals import REFERRAL_CATEGORY_CODE, REFERRAL_FACILITY_SYSTEM

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/imaging", tags=["imaging"])

IMAGING_CATEGORY_CODE = "363679005"  # SNOMED "Imaging" (set by the imaging write-back)
TRIAGE_EXT = "https://fhir.medagent.health.lk/ext/imaging-triage"
_CONFIDENCE_FLOOR = 0.50  # below this, force a radiologist review

# Curated triage ruleset (clinician-owned in prod). Findings are matched case-
# insensitively as substrings of the AI/reporter finding text + impression.
_CRITICAL = [
    "pneumothorax", "tension pneumothorax", "haemorrhage", "hemorrhage", "midline shift",
    "aortic dissection", "free air", "pneumoperitoneum", "pulmonary embolism", "embolism",
    "acute infarct", "large mass", "mass effect", "displaced fracture", "perforation",
]
_ABNORMAL = [
    "nodule", "opacity", "consolidation", "effusion", "cardiomegaly", "lesion",
    "degenerative", "fracture", "atelectasis", "infiltrate", "enlarged",
]
# Routing: which specialty an urgent finding of each modality goes to.
_ROUTE = {
    "ct-head": "Neurosurgery", "mri-head": "Neurosurgery",
    "cxr": "Respiratory", "chest": "Respiratory",
    "abdomen": "General surgery", "spine": "Orthopaedics",
}


def _classify(findings: list[str], impression: str, min_confidence: float) -> tuple[str, list[str], bool]:
    """Return (flag, matched_terms, needs_review). Deterministic keyword ruleset."""
    hay = " ".join(findings + [impression]).lower()
    crit = [k for k in _CRITICAL if k in hay]
    if crit:
        flag = "urgent"
        matched = crit
    else:
        abn = [k for k in _ABNORMAL if k in hay]
        flag, matched = ("abnormal", abn) if abn else ("normal", [])
    needs_review = min_confidence < _CONFIDENCE_FLOOR
    return flag, matched, needs_review


class Finding(BaseModel):
    text: str = Field(..., min_length=1)
    confidence: float | None = Field(default=None, ge=0, le=1)


class ImagingReport(BaseModel):
    modality: str = Field(..., min_length=1, description="e.g. cxr, ct-head, mri-head")
    body_site: str = Field(..., min_length=1)
    findings: list[Finding] = Field(default_factory=list)
    impression: str = Field("", description="Radiologist/AI impression text")
    ai_source: str | None = None  # e.g. "chest-triage-v2"
    route_facility: str | None = None  # urgent routing target (defaults applied)
    route_specialty: str | None = None


@router.post("/{service_request_id}/report", status_code=status.HTTP_201_CREATED)
async def attach_report(
    service_request_id: str,
    body: ImagingReport,
    request: Request,
    principal: Annotated[Principal, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """Attach an imaging study + report to an order, triage it, and auto-route an
    urgent finding into the referral inbox (FR-10.1/10.3)."""
    auth = request.headers.get("authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else None
    fhir = FHIRClient(settings.fhir_base_url)
    try:
        try:
            sr = await fhir.read("ServiceRequest", service_request_id)
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=404, detail="imaging order not found")
        subject = sr.get("subject", {})
        pref = subject.get("reference", "")
        if not pref.startswith("Patient/"):
            raise HTTPException(status_code=422, detail="order has no patient subject")
        pid = pref.split("/", 1)[1]
        now = datetime.now(timezone.utc).isoformat()

        finding_texts = [f.text for f in body.findings]
        confs = [f.confidence for f in body.findings if f.confidence is not None]
        min_conf = min(confs) if confs else 1.0
        flag, matched, needs_review = _classify(finding_texts, body.impression, min_conf)

        study = await fhir.create("ImagingStudy", {
            "resourceType": "ImagingStudy", "status": "available",
            "subject": {"reference": pref}, "started": now,
            "basedOn": [{"reference": f"ServiceRequest/{service_request_id}"}],
            "description": f"{body.modality} {body.body_site}",
        }, token)
        study_id = str(study["id"])

        report = await fhir.create("DiagnosticReport", {
            "resourceType": "DiagnosticReport", "status": "final",
            "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v2-0074",
                                      "code": "RAD", "display": "Radiology"}]}],
            "code": {"text": f"{body.modality} {body.body_site}"},
            "subject": {"reference": pref}, "effectiveDateTime": now, "issued": now,
            "basedOn": [{"reference": f"ServiceRequest/{service_request_id}"}],
            "imagingStudy": [{"reference": f"ImagingStudy/{study_id}"}],
            "conclusion": body.impression or "; ".join(finding_texts) or "No findings recorded",
            "extension": [{"url": TRIAGE_EXT, "extension": [
                {"url": "flag", "valueString": flag},
                {"url": "needsReview", "valueBoolean": needs_review},
                {"url": "matched", "valueString": ", ".join(matched)},
                {"url": "aiSource", "valueString": body.ai_source or ""},
                {"url": "minConfidence", "valueDecimal": min_conf},
            ]}],
        }, token)
        report_id = str(report["id"])

        # Close the imaging order.
        sr["status"] = "completed"
        await fhir.update("ServiceRequest", service_request_id, sr, token)

        referral = None
        if flag == "urgent":
            specialty = body.route_specialty or _ROUTE.get(body.modality.lower()) \
                or _ROUTE.get(body.body_site.lower()) or "Radiology urgent review"
            facility = body.route_facility or "teaching-hospital"
            sr_ref = await fhir.create("ServiceRequest", {
                "resourceType": "ServiceRequest", "status": "active", "intent": "order",
                "priority": "urgent",
                "category": [{"coding": [{"system": "http://snomed.info/sct",
                                          "code": REFERRAL_CATEGORY_CODE, "display": "Patient referral"}]}],
                "code": {"text": specialty}, "subject": {"reference": pref}, "authoredOn": now,
                "reasonCode": [{"text": f"Urgent imaging finding: {', '.join(matched)}"}],
                "supportingInfo": [{"reference": f"DiagnosticReport/{report_id}"}],
            }, token)
            task = await fhir.create("Task", {
                "resourceType": "Task", "status": "requested", "intent": "order", "priority": "urgent",
                "meta": {"tag": [{"system": REFERRAL_FACILITY_SYSTEM, "code": facility}]},
                "code": {"text": specialty}, "focus": {"reference": f"ServiceRequest/{sr_ref['id']}"},
                "for": {"reference": pref}, "authoredOn": now,
                "requester": {"display": principal.subject},
                "reasonCode": {"text": f"Urgent imaging finding: {', '.join(matched)}"},
            }, token)
            referral = {"task_id": str(task["id"]), "to_facility": facility, "specialty": specialty}
            session.add(AuditOutbox(event={
                "type": "imaging_urgent_flag", "actor": principal.subject, "patient_fhir_id": pid,
                "committed": f"DiagnosticReport/{report_id}", "matched": matched,
                "routed_to": facility, "specialty": specialty,
            }))

        session.add(AuditOutbox(event={
            "type": "imaging_reported", "actor": principal.subject, "patient_fhir_id": pid,
            "committed": f"DiagnosticReport/{report_id}", "flag": flag, "needs_review": needs_review,
        }))
        return {"report": f"DiagnosticReport/{report_id}", "study": f"ImagingStudy/{study_id}",
                "triage": {"flag": flag, "matched": matched, "needs_review": needs_review,
                           "min_confidence": min_conf},
                "referral": referral}
    finally:
        await fhir.close()


def _triage_of(report: dict[str, Any]) -> dict[str, Any]:
    for e in report.get("extension", []):
        if e.get("url") == TRIAGE_EXT:
            out: dict[str, Any] = {}
            for x in e.get("extension", []):
                out[x["url"]] = x.get("valueString", x.get("valueBoolean", x.get("valueDecimal")))
            return out
    return {}


@router.get("/reports", response_model=ImagingReports)
async def imaging_reports(
    principal: Annotated[Principal, Depends(require_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    patient: Annotated[str, Query(min_length=1, description="PHN or FHIR id")],
) -> dict[str, Any]:
    """A patient's imaging reports with their triage flags (FR-10.2)."""
    fhir = FHIRClient(settings.fhir_base_url)
    try:
        p = await _resolve_pid(fhir, patient)
        if not p:
            raise HTTPException(status_code=404, detail=f"no FHIR patient for {patient}")
        pid = str(p["id"])
        reports = await fhir.search("DiagnosticReport",
                                    {"patient": pid, "category": "RAD", "_sort": "-date", "_count": "100"})
        out = []
        for r in reports:
            t = _triage_of(r)
            if not t:  # imaging reports only (skip non-triaged)
                continue
            out.append({"ref": f"DiagnosticReport/{r.get('id')}",
                        "code": (r.get("code") or {}).get("text"),
                        "conclusion": r.get("conclusion"), "issued": r.get("issued"),
                        "flag": t.get("flag"), "needs_review": t.get("needsReview"),
                        "matched": t.get("matched")})
        # urgent first, then abnormal, then normal
        order = {"urgent": 0, "abnormal": 1, "normal": 2}
        out.sort(key=lambda x: order.get(x.get("flag"), 3))
        return {"patient": f"Patient/{pid}", "count": len(out), "reports": out}
    finally:
        await fhir.close()

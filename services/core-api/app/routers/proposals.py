"""Write-back with sign-off (FR-4.3/4.8/4.9, 04 §2.2).

A clinician commits a structured proposal — diagnosis, prescription, note, or
vitals — which is written to FHIR and audited. Prescriptions are RE-SCREENED by
the deterministic Rx-safety engine (agent-service) at commit time, regardless of
what the UI showed: a `block` cannot be committed; a `warn` requires an explicit,
audited override reason. Every commit writes an AuditEvent (via the outbox).
Step-up (acr=loa2) is required for prescriptions when enforced (02 §5.2).
"""

from __future__ import annotations

import logging
from typing import Annotated, Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import Principal, require_user
from app.config import Settings
from app.deps import get_session, get_settings
from app.fhir_client import FHIRClient
from app.models import AuditOutbox

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/proposals", tags=["write-back"])

PHN_SYSTEM = "https://fhir.medagent.health.lk/id/phn"
RX_VERDICT_EXT = "https://fhir.medagent.health.lk/ext/rx-safety-verdict"


class CommitRequest(BaseModel):
    kind: Literal["prescription", "diagnosis", "note", "vitals"]
    patient: str = Field(min_length=1, description="PHN or FHIR Patient id")
    encounter_id: str | None = None
    payload: dict[str, Any]
    override_reason: str | None = None  # required to commit a `warn` prescription


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


async def _resolve_patient(fhir: FHIRClient, ref: str) -> str | None:
    if ref.isdigit():
        rows = await fhir.search("Patient", {"identifier": f"{PHN_SYSTEM}|{ref}"})
        if rows:
            return str(rows[0]["id"])
    try:
        p = await fhir.read("Patient", ref)
        return str(p["id"])
    except httpx.HTTPStatusError:
        return None


async def _screen_rx(
    settings: Settings, fhir: FHIRClient, pid: str, drug: str, dose_mg_per_day: float | None, token: str | None
) -> dict[str, Any]:
    meds = await fhir.search("MedicationRequest", {"patient": pid, "status": "active"})
    allergies = await fhir.search("AllergyIntolerance", {"patient": pid})
    body = {
        "proposed_drug": drug,
        "current_meds": [_cc_text(m.get("medicationCodeableConcept")) for m in meds],
        "allergies": [
            {"substance": _cc_text(a.get("code")), "criticality": a.get("criticality", "unknown")}
            for a in allergies
        ],
        "dose_mg_per_day": dose_mg_per_day,
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{settings.agent_service_url.rstrip('/')}/api/v1/rx-safety/screen",
            json=body,
            headers={"Authorization": f"Bearer {token}"} if token else {},
        )
    if resp.status_code != 200:
        # Cannot obtain a verdict -> fail closed.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="rx-safety screening unavailable; prescription blocked (fail-closed)",
        )
    return dict(resp.json())


def _build_resource(kind: str, pid: str, payload: dict[str, Any], principal: Principal,
                    encounter_id: str | None, verdict: dict[str, Any] | None) -> tuple[str, dict[str, Any]]:
    subject = {"reference": f"Patient/{pid}"}
    enc = {"reference": f"Encounter/{encounter_id}"} if encounter_id else None
    if kind == "prescription":
        res: dict[str, Any] = {
            "resourceType": "MedicationRequest",
            "status": "active",
            "intent": "order",
            "medicationCodeableConcept": {"text": payload["drug"]},
            "subject": subject,
            "requester": {"display": principal.subject},
        }
        if payload.get("dose_text"):
            res["dosageInstruction"] = [{"text": payload["dose_text"]}]
        if verdict:
            ext = [
                {"url": "verdict", "valueString": verdict.get("verdict", "")},
                {"url": "datasetVersion", "valueString": verdict.get("dataset_version", "")},
            ]
            if payload.get("override_reason_applied"):
                ext.append({"url": "overrideReason", "valueString": payload["override_reason_applied"]})
            res["extension"] = [{"url": RX_VERDICT_EXT, "extension": ext}]
        if enc:
            res["encounter"] = enc
        return "MedicationRequest", res
    if kind == "diagnosis":
        code: dict[str, Any] = {"text": payload["text"]}
        if payload.get("icd10"):
            code["coding"] = [{"system": "http://hl7.org/fhir/sid/icd-10", "code": payload["icd10"]}]
        res = {
            "resourceType": "Condition",
            "clinicalStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                                           "code": payload.get("clinical_status", "active")}]},
            "code": code,
            "subject": subject,
            "recorder": {"display": principal.subject},
        }
        if enc:
            res["encounter"] = enc
        return "Condition", res
    if kind == "vitals":
        code = {"text": payload.get("code_text", "Vital sign")}
        if payload.get("loinc"):
            code["coding"] = [{"system": "http://loinc.org", "code": payload["loinc"]}]
        res = {
            "resourceType": "Observation",
            "status": "final",
            "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category",
                                      "code": "vital-signs"}]}],
            "code": code,
            "subject": subject,
            "valueQuantity": {"value": payload["value"], "unit": payload.get("unit", ""),
                              "system": "http://unitsofmeasure.org", "code": payload.get("unit", "")},
        }
        if enc:
            res["encounter"] = enc
        return "Observation", res
    # note
    res = {
        "resourceType": "DocumentReference",
        "status": "current",
        "type": {"text": payload.get("type_text", "Clinical note")},
        "subject": subject,
        "description": payload["text"],
    }
    return "DocumentReference", res


@router.post("/commit", status_code=status.HTTP_201_CREATED)
async def commit(
    body: CommitRequest,
    request: Request,
    principal: Annotated[Principal, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    token = _bearer(request)
    fhir = FHIRClient(settings.fhir_base_url)
    try:
        pid = await _resolve_patient(fhir, body.patient)
        if not pid:
            raise HTTPException(status_code=404, detail=f"no FHIR patient for {body.patient}")

        verdict: dict[str, Any] | None = None
        if body.kind == "prescription":
            # Step-up gate (02 §5.2) — enforced when configured.
            if settings.step_up_enforced and str(principal.claims.get("acr", "")) not in ("loa2", "2"):
                raise HTTPException(status_code=401, detail="step_up_required (acr=loa2) for prescribing")
            drug = body.payload.get("drug")
            if not drug:
                raise HTTPException(status_code=422, detail="prescription payload requires 'drug'")
            verdict = await _screen_rx(
                settings, fhir, pid, drug, body.payload.get("dose_mg_per_day"), token
            )
            if verdict["verdict"] == "block":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"error": "rx_safety_block", "verdict": verdict},
                )
            if verdict["verdict"] == "warn" and not body.override_reason:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={"error": "override_reason_required", "verdict": verdict},
                )
            if body.override_reason:
                body.payload["override_reason_applied"] = body.override_reason

        resource_type, resource = _build_resource(
            body.kind, pid, body.payload, principal, body.encounter_id, verdict
        )
        created = await fhir.create(resource_type, resource, token)
        ref = f"{resource_type}/{created.get('id')}"

        session.add(AuditOutbox(event={
            "type": "proposal_committed",
            "kind": body.kind,
            "actor": principal.subject,
            "patient_fhir_id": pid,
            "committed": ref,
            "rx_verdict": verdict.get("verdict") if verdict else None,
            "override_reason": body.override_reason,
        }))
        logger.info("proposal committed", extra={"kind": body.kind, "ref": ref})
        return {"committed": ref, "verdict": verdict}
    finally:
        await fhir.close()

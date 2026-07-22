"""Patient registration + demographic search (MPI v1, 02 §8, FR-2.4).

S1 skeleton: registration issues a PHN through the real MPI issuance path;
search is a SQL ILIKE skeleton over normalised fields. Probabilistic dedup
scoring and the FHIR Patient projection land later in S1/S2.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import Principal, require_user
from app.config import Settings
from app.deps import get_session, get_settings
from app.fhir_client import FHIRClient
from app.models import AuditOutbox, PatientMPI
from app.mpi import phn as phn_mod

PHN_SYSTEM = "https://fhir.medagent.health.lk/id/phn"


def _cc_text(cc: dict[str, Any] | None) -> str:
    if not cc:
        return ""
    if cc.get("text"):
        return cc["text"]
    for c in cc.get("coding", []):
        return c.get("display") or c.get("code") or ""
    return ""

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/patients", tags=["patients"])

_PHN_ISSUE_RETRIES = 3


class RegisterPatientRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    nic: str | None = None
    phone: str | None = None
    demographics: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional demographic fields (dob, sex, address_gn, ...).",
    )


class PatientOut(BaseModel):
    id: UUID
    phn: str
    phn_display: str
    nic: str | None
    demographics: dict[str, Any]
    face_consent: bool


def _to_out(row: PatientMPI) -> PatientOut:
    return PatientOut(
        id=row.id,
        phn=row.phn,
        phn_display=phn_mod.format_phn(row.phn),
        nic=row.nic,
        demographics=row.demographics,
        face_consent=row.face_consent,
    )


@router.post("", status_code=status.HTTP_201_CREATED, response_model=PatientOut)
async def register_patient(
    body: RegisterPatientRequest,
    principal: Annotated[Principal, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PatientOut:
    """Register a patient: issue a PHN via the MPI and create the index row.

    TODO(S1): dedup candidate matching before create (02 §8.3);
    FHIR `Patient` projection after create.
    """
    demographics = {"name": body.name, "phone": body.phone, **body.demographics}

    row: PatientMPI | None = None
    for _ in range(_PHN_ISSUE_RETRIES):
        candidate = PatientMPI(
            phn=phn_mod.generate_phn(),
            nic=body.nic,
            demographics=demographics,
        )
        session.add(candidate)
        try:
            await session.flush()
        except IntegrityError:
            # PHN collision (astronomically rare) — retry with a fresh number.
            await session.rollback()
            continue
        row = candidate
        break
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="could not issue a unique PHN",
        )

    session.add(
        AuditOutbox(
            event={
                "type": "patient_registered",
                "actor": principal.subject,
                "patient_id": str(row.id),
                # Opaque IDs only — no name/NIC/phone in audit payloads or logs.
            }
        )
    )
    logger.info("patient registered", extra={"patient_id": str(row.id)})
    return _to_out(row)


@router.get("", response_model=list[PatientOut])
async def search_patients(
    principal: Annotated[Principal, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    name: Annotated[str | None, Query(min_length=2)] = None,
    phn: Annotated[str | None, Query()] = None,
    phone: Annotated[str | None, Query(min_length=3)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[PatientOut]:
    """Demographic search by name / PHN / phone (FR-2.4).

    Returns demographics only — opening the clinical record still requires a
    care-relationship grant (02 §7). S1: SQL ILIKE skeleton; normalised
    dual-script name columns and blocking keys come with dedup work.
    """
    if not any([name, phn, phone]):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="provide at least one of: name, phn, phone",
        )

    query = select(PatientMPI).limit(limit)
    if phn is not None:
        canonical = phn_mod.normalize_phn(phn)
        # Check-digit validated before the query hits the DB (02 §8.3).
        if not phn_mod.validate_phn(canonical):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="invalid PHN (check digit)",
            )
        query = query.where(PatientMPI.phn == canonical)
    if name is not None:
        query = query.where(PatientMPI.demographics["name"].astext.ilike(f"%{name}%"))
    if phone is not None:
        query = query.where(
            or_(
                PatientMPI.demographics["phone"].astext.ilike(f"%{phone}%"),
                PatientMPI.nic == phone,  # NIC typed in the phone box is a common desk reality
            )
        )

    rows = (await session.execute(query)).scalars().all()
    return [_to_out(r) for r in rows]


@router.get("/{phn}/summary")
async def patient_summary(
    phn: str,
    principal: Annotated[Principal, Depends(require_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """Compact clinical summary from FHIR (FR-2.2 doctor card / FR-5.3 patient portal):
    demographics, active problems, active medications, allergies, recent vitals,
    upcoming appointments. Read-only."""
    fhir = FHIRClient(settings.fhir_base_url)
    try:
        matches = await fhir.search("Patient", {"identifier": f"{PHN_SYSTEM}|{phn}"})
        if not matches:
            raise HTTPException(status_code=404, detail="patient not found")
        patient = matches[0]
        pid = str(patient["id"])
        name = (patient.get("name") or [{}])[0]
        full = " ".join(name.get("given", []) + [name.get("family", "")]).strip()

        conditions = await fhir.search("Condition", {"patient": pid, "clinical-status": "active"})
        meds = await fhir.search("MedicationRequest", {"patient": pid, "status": "active"})
        allergies = await fhir.search("AllergyIntolerance", {"patient": pid})
        vitals = await fhir.search(
            "Observation", {"patient": pid, "category": "vital-signs", "_sort": "-date", "_count": "5"}
        )
        appts = await fhir.search("Appointment", {"patient": pid, "status": "booked", "_sort": "date"})

        return {
            "patient": {"phn": phn, "name": full or "Unknown", "gender": patient.get("gender"),
                        "birthDate": patient.get("birthDate")},
            "problems": [{"text": _cc_text(c.get("code")), "ref": f"Condition/{c.get('id')}"} for c in conditions],
            "medications": [{"text": _cc_text(m.get("medicationCodeableConcept")),
                             "ref": f"MedicationRequest/{m.get('id')}"} for m in meds],
            "allergies": [{"text": _cc_text(a.get("code")), "criticality": a.get("criticality", "unknown"),
                           "ref": f"AllergyIntolerance/{a.get('id')}"} for a in allergies],
            "vitals": [{"text": _cc_text(o.get("code")),
                        "value": (o.get("valueQuantity") or {}).get("value"),
                        "unit": (o.get("valueQuantity") or {}).get("unit"),
                        "when": o.get("effectiveDateTime")} for o in vitals],
            "appointments": [{"start": ap.get("start"), "status": ap.get("status")} for ap in appts],
        }
    finally:
        await fhir.close()

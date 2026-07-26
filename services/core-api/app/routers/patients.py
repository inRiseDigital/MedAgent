"""Patient registration + demographic search (MPI v1, 02 §8, FR-2.4).

S1 skeleton: registration issues a PHN through the real MPI issuance path;
search is a SQL ILIKE skeleton over normalised fields. Probabilistic dedup
scoring and the FHIR Patient projection land later in S1/S2.
"""

from __future__ import annotations

import html
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Any
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse
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


BIRTH_REG_SYSTEM = "https://fhir.medagent.health.lk/id/birth-registration"
GUARDIAN_EXT = "https://fhir.medagent.health.lk/ext/guardian"


class BirthEnrolRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    sex: str = "unknown"                 # male | female | other | unknown
    birth_date: str                      # YYYY-MM-DD
    mother_phn: str = Field(min_length=1)
    birth_registration_no: str | None = None


@router.post("/newborn", status_code=status.HTTP_201_CREATED)
async def enrol_newborn(
    body: BirthEnrolRequest,
    request: Request,
    principal: Annotated[Principal, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """Create a lifetime profile at birth (FR-7.1/7.2, backlog 4.1): issue a PHN,
    create the FHIR Patient, link to the mother, and grant a time-bound guardian
    proxy (expires at majority). SLUDI links later via the reserved adapter."""
    auth = request.headers.get("authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else None
    fhir = FHIRClient(settings.fhir_base_url)
    try:
        mothers = await fhir.search("Patient", {"identifier": f"{PHN_SYSTEM}|{body.mother_phn}"})
        if not mothers:
            raise HTTPException(status_code=404, detail=f"mother not found for PHN {body.mother_phn}")
        mn = (mothers[0].get("name") or [{}])[0]
        mother_name = mn.get("text") or " ".join(mn.get("given", []) + [mn.get("family", "")]).strip() or "Mother"

        # Issue the newborn's PHN via the MPI (same path as registration).
        row: PatientMPI | None = None
        for _ in range(_PHN_ISSUE_RETRIES):
            candidate = PatientMPI(
                phn=phn_mod.generate_phn(),
                demographics={"name": body.name, "sex": body.sex, "dob": body.birth_date,
                              "mother_phn": body.mother_phn},
            )
            session.add(candidate)
            try:
                await session.flush()
            except IntegrityError:
                await session.rollback()
                continue
            row = candidate
            break
        if row is None:
            raise HTTPException(status_code=500, detail="could not issue a unique PHN")
        newborn_phn = row.phn

        identifiers = [{"system": PHN_SYSTEM, "value": newborn_phn}]
        if body.birth_registration_no:
            identifiers.append({"system": BIRTH_REG_SYSTEM, "value": body.birth_registration_no})
        created = await fhir.create("Patient", {
            "resourceType": "Patient",
            "identifier": identifiers,
            "name": [{"text": body.name}],
            "gender": body.sex,
            "birthDate": body.birth_date,
        }, token)
        newborn_fid = str(created["id"])

        # Guardian proxy (the mother), time-bound to majority (birth year + 18).
        try:
            majority = f"{int(body.birth_date[:4]) + 18}{body.birth_date[4:]}"
        except ValueError:
            majority = None
        rp = await fhir.create("RelatedPerson", {
            "resourceType": "RelatedPerson",
            "patient": {"reference": f"Patient/{newborn_fid}"},
            "relationship": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v3-RoleCode",
                                          "code": "MTH", "display": "mother"}]}],
            "name": [{"text": mother_name}],
            "identifier": [{"system": PHN_SYSTEM, "value": body.mother_phn}],
            "extension": [{"url": GUARDIAN_EXT, "extension": (
                [{"url": "rights", "valueString": "proxy-full"}]
                + ([{"url": "expiresAt", "valueDate": majority}] if majority else [])
            )}],
        }, token)

        session.add(AuditOutbox(event={
            "type": "birth_enrolment", "actor": principal.subject,
            "patient_fhir_id": newborn_fid, "committed": f"Patient/{newborn_fid}",
            "mother_phn_last4": body.mother_phn[-4:],
        }))
        logger.info("newborn enrolled", extra={"patient_id": str(row.id)})
        return {
            "newborn_phn": newborn_phn,
            "newborn_phn_display": phn_mod.format_phn(newborn_phn),
            "newborn_fhir_id": newborn_fid,
            "guardian": f"RelatedPerson/{rp.get('id')}",
            "guardian_of": mother_name,
            "guardian_expires": majority,
        }
    finally:
        await fhir.close()


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


async def _load_summary(fhir: FHIRClient, phn: str) -> tuple[dict[str, Any], str]:
    """Build the compact clinical summary from FHIR. Returns (summary, patient_fhir_id).
    Raises 404 if the PHN has no Patient projection. Shared by the JSON summary
    (FR-2.2/5.3) and the printable/export document (FR-5.6)."""
    matches = await fhir.search("Patient", {"identifier": f"{PHN_SYSTEM}|{phn}"})
    if not matches:
        raise HTTPException(status_code=404, detail="patient not found")
    patient = matches[0]
    pid = str(patient["id"])
    name = (patient.get("name") or [{}])[0]
    full = name.get("text") or " ".join(name.get("given", []) + [name.get("family", "")]).strip()

    conditions = await fhir.search("Condition", {"patient": pid, "clinical-status": "active"})
    meds = await fhir.search("MedicationRequest", {"patient": pid, "status": "active"})
    allergies = await fhir.search("AllergyIntolerance", {"patient": pid})
    vitals = await fhir.search(
        "Observation", {"patient": pid, "category": "vital-signs", "_sort": "-date", "_count": "5"}
    )
    appts = await fhir.search("Appointment", {"patient": pid, "status": "booked", "_sort": "date"})
    reports = await fhir.search(
        "DiagnosticReport", {"patient": pid, "_sort": "-issued", "_count": "5"}
    )

    summary = {
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
        "results": [{"text": _cc_text(r.get("code")), "conclusion": r.get("conclusion"),
                     "critical": bool(r.get("conclusion") and "CRITICAL" in r["conclusion"]),
                     "ref": f"DiagnosticReport/{r.get('id')}"} for r in reports],
    }
    return summary, pid


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
        summary, _pid = await _load_summary(fhir, phn)
        return summary
    finally:
        await fhir.close()


@router.get("/{phn}/brief")
async def patient_brief(
    phn: str,
    request: Request,
    principal: Annotated[Principal, Depends(require_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """Ambient clinical brief for patient-open (FR-2.2, backlog 3.1): a headline
    plus PROACTIVE safety flags computed deterministically from the record —
    high-risk allergies, drug interactions / allergy conflicts among the ACTIVE
    medications (via the Rx-safety engine), and critical lab results. No typing,
    no LLM required; the assistant only narrates this in live mode."""
    fhir = FHIRClient(settings.fhir_base_url)
    try:
        summary, _pid = await _load_summary(fhir, phn)
    finally:
        await fhir.close()

    flags: list[dict[str, Any]] = []
    for a in summary["allergies"]:
        if a.get("criticality") == "high":
            flags.append({"severity": "block", "kind": "allergy",
                          "text": f"High-risk allergy: {a['text']}", "cite": a["ref"]})

    med_names = [m["text"] for m in summary["medications"] if m["text"]]
    allergies = [{"substance": a["text"], "criticality": a.get("criticality", "unknown")}
                 for a in summary["allergies"]]
    auth = request.headers.get("authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else None
    if med_names:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{settings.agent_service_url.rstrip('/')}/api/v1/rx-safety/review",
                    json={"meds": med_names, "allergies": allergies},
                    headers={"Authorization": f"Bearer {token}"} if token else {},
                )
            if resp.status_code == 200:
                for f in resp.json().get("flags", []):
                    flags.append({
                        "severity": f.get("severity", "warn"), "kind": "medication",
                        "text": f"{f.get('drug', '')}: {f.get('rationale', '')}".strip(": "),
                        "code": f.get("code"),
                    })
        except Exception:  # noqa: BLE001 — brief is best-effort; never block the page
            logger.exception("rx-safety review unavailable for brief")

    for res in summary.get("results", []):
        if res.get("critical"):
            flags.append({"severity": "block", "kind": "lab",
                          "text": f"Critical result: {res['text']}", "cite": res["ref"]})

    n_problems, n_meds = len(summary["problems"]), len(med_names)
    p = summary["patient"]
    return {
        "headline": f"{p['name']} · {n_problems} active problem(s) · {n_meds} medication(s)",
        "problems": [x["text"] for x in summary["problems"]],
        "flags": flags,
    }


# --- Immunization engine (FR-7.3, backlog 4.2) ------------------------------
# Sri Lanka national EPI schedule (curated pilot subset). Due date = birth +
# months. Given doses are FHIR Immunization resources tagged with the schedule
# key; status is computed against today.
IMMUNIZATION_KEY_SYSTEM = "https://fhir.medagent.health.lk/id/immunization-key"
EPI_SCHEDULE = [
    {"key": "bcg", "name": "BCG", "months": 0},
    {"key": "opv0", "name": "OPV (birth dose)", "months": 0},
    {"key": "penta1", "name": "Pentavalent 1 (DTP-HepB-Hib) + OPV 1", "months": 2},
    {"key": "penta2", "name": "Pentavalent 2 + OPV 2", "months": 4},
    {"key": "penta3", "name": "Pentavalent 3 + OPV 3", "months": 6},
    {"key": "mmr1", "name": "MMR 1", "months": 9},
    {"key": "je", "name": "Live JE", "months": 12},
    {"key": "dtp_booster", "name": "DTP booster + OPV + MMR 2", "months": 18},
]


def _add_months(d: date, months: int) -> date:
    m = d.month - 1 + months
    y, mo = d.year + m // 12, m % 12 + 1
    leap = y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)
    last = [31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][mo - 1]
    return date(y, mo, min(d.day, last))


async def _resolve_pid(fhir: FHIRClient, phn: str) -> dict[str, Any] | None:
    rows = await fhir.search("Patient", {"identifier": f"{PHN_SYSTEM}|{phn}"})
    return rows[0] if rows else None


@router.get("/{phn}/immunizations")
async def immunizations(
    phn: str,
    principal: Annotated[Principal, Depends(require_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """The child's immunization schedule with status (given / overdue / due-soon /
    upcoming) — auto-generated from the birth date against the EPI schedule."""
    fhir = FHIRClient(settings.fhir_base_url)
    try:
        patient = await _resolve_pid(fhir, phn)
        if not patient:
            raise HTTPException(status_code=404, detail=f"no FHIR patient for {phn}")
        pid = str(patient["id"])
        bd = date.fromisoformat(patient["birthDate"]) if patient.get("birthDate") else None
        given = await fhir.search("Immunization", {"patient": pid})
        given_on: dict[str, str] = {}
        for im in given:
            for ident in im.get("identifier", []):
                if ident.get("system") == IMMUNIZATION_KEY_SYSTEM:
                    given_on[ident["value"]] = im.get("occurrenceDateTime", "")
        today = datetime.now(timezone.utc).date()
        rows, overdue = [], 0
        for v in EPI_SCHEDULE:
            due = _add_months(bd, v["months"]) if bd else None
            if v["key"] in given_on:
                st = "given"
            elif due is None:
                st = "unknown"
            elif due < today:
                st, overdue = "overdue", overdue + 1
            elif due <= today + timedelta(days=30):
                st = "due-soon"
            else:
                st = "upcoming"
            rows.append({"key": v["key"], "name": v["name"],
                         "due": due.isoformat() if due else None,
                         "status": st, "given_on": given_on.get(v["key"])})
        return {"schedule": rows, "overdue": overdue}
    finally:
        await fhir.close()


class GiveVaccineRequest(BaseModel):
    key: str
    date: str | None = None  # ISO date; defaults to today


@router.post("/{phn}/immunizations", status_code=status.HTTP_201_CREATED)
async def record_immunization(
    phn: str,
    body: GiveVaccineRequest,
    request: Request,
    principal: Annotated[Principal, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """Record a given dose as a completed FHIR Immunization (FR-7.3), audited."""
    auth = request.headers.get("authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else None
    v = next((x for x in EPI_SCHEDULE if x["key"] == body.key), None)
    if not v:
        raise HTTPException(status_code=422, detail=f"unknown vaccine key '{body.key}'")
    occ = body.date or datetime.now(timezone.utc).date().isoformat()
    fhir = FHIRClient(settings.fhir_base_url)
    try:
        patient = await _resolve_pid(fhir, phn)
        if not patient:
            raise HTTPException(status_code=404, detail=f"no FHIR patient for {phn}")
        pid = str(patient["id"])
        im = await fhir.create("Immunization", {
            "resourceType": "Immunization",
            "status": "completed",
            "vaccineCode": {"text": v["name"]},
            "patient": {"reference": f"Patient/{pid}"},
            "occurrenceDateTime": occ,
            "identifier": [{"system": IMMUNIZATION_KEY_SYSTEM, "value": body.key}],
        }, token)
        session.add(AuditOutbox(event={
            "type": "immunization_recorded", "actor": principal.subject,
            "patient_fhir_id": pid, "committed": f"Immunization/{im.get('id')}", "vaccine": body.key,
        }))
        return {"recorded": f"Immunization/{im.get('id')}", "vaccine": v["name"], "date": occ}
    finally:
        await fhir.close()


def _li(items: list[str]) -> str:
    """Render a <ul> from pre-escaped list items, or a muted 'None recorded'."""
    if not items:
        return '<p class="muted">None recorded</p>'
    return "<ul>" + "".join(f"<li>{it}</li>" for it in items) + "</ul>"


def _render_summary_html(summary: dict[str, Any], *, doc_id: str, generated: str, actor: str) -> str:
    """Self-contained, print-optimised visit-summary document (FR-5.6, 07 §8).

    Facility branding, a generation timestamp, a requesting-identity watermark and
    a document ID, so a printed/saved copy is self-describing and traceable. No
    external assets — opens in a tab; the browser's Print → Save as PDF produces
    the shareable file. (Production adds a server-side PDF binary + registration
    as a FHIR DocumentReference in object storage — 03 §8.1, 07 §8.)
    """
    p = summary["patient"]
    esc = html.escape
    problems = _li([esc(x["text"]) for x in summary["problems"] if x["text"]])
    meds = _li([esc(x["text"]) for x in summary["medications"] if x["text"]])
    allergies = _li(
        [f'{esc(x["text"])} <span class="crit">({esc(str(x["criticality"]))})</span>'
         for x in summary["allergies"] if x["text"]]
    )
    vitals = _li(
        [f'{esc(v["text"])}: {esc(str(v["value"]))} {esc(str(v.get("unit") or ""))}'
         f'<span class="muted"> · {esc(str(v.get("when") or ""))}</span>'
         for v in summary["vitals"] if v.get("value") is not None]
    )
    appts = _li([esc(str(a["start"] or "")) for a in summary["appointments"] if a.get("start")])
    dob = esc(str(p.get("birthDate") or "—"))
    sex = esc(str(p.get("gender") or "—"))

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Visit summary · {esc(p["name"])}</title>
<style>
  :root {{ color-scheme: light; }}
  * {{ box-sizing: border-box; }}
  body {{ font: 14px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
         color: #1a1a1a; max-width: 780px; margin: 24px auto; padding: 0 24px; }}
  header {{ display: flex; justify-content: space-between; align-items: flex-start;
            border-bottom: 2px solid #0b6b5b; padding-bottom: 12px; margin-bottom: 8px; }}
  .brand {{ font-size: 18px; font-weight: 700; color: #0b6b5b; }}
  .brand small {{ display:block; font-weight:400; color:#555; font-size:12px; }}
  .docmeta {{ text-align: right; font-size: 11px; color: #666; }}
  .watermark {{ font-size: 11px; color: #888; margin: 4px 0 16px; }}
  h1 {{ font-size: 20px; margin: 8px 0 2px; }}
  h2 {{ font-size: 14px; text-transform: uppercase; letter-spacing: .04em;
        color: #0b6b5b; margin: 18px 0 6px; border-bottom: 1px solid #e2e2e2; }}
  .demo {{ color: #444; margin: 0 0 4px; }}
  ul {{ margin: 4px 0; padding-left: 20px; }}
  li {{ margin: 2px 0; }}
  .muted {{ color: #999; margin: 4px 0; }}
  .crit {{ color: #b00020; font-weight: 600; }}
  .print-hint {{ margin: 20px 0; }}
  button {{ font: inherit; padding: 8px 16px; border: 1px solid #0b6b5b; background:#0b6b5b;
            color:#fff; border-radius: 6px; cursor: pointer; }}
  footer {{ margin-top: 28px; padding-top: 10px; border-top: 1px solid #e2e2e2;
            font-size: 11px; color: #777; }}
  @media print {{ .print-hint {{ display: none; }} body {{ margin: 0; }} }}
</style></head>
<body>
  <header>
    <div class="brand">MedAgent Health<small>National Digital Health Platform · Sri Lanka</small></div>
    <div class="docmeta">Document {esc(doc_id)}<br>Generated {esc(generated)}</div>
  </header>
  <div class="watermark">Generated for {esc(actor)} · not a legal medical record · verify against the source system</div>

  <h1>Visit summary — {esc(p["name"])}</h1>
  <p class="demo">PHN {esc(phn_mod.format_phn(p["phn"]))} · DOB {dob} · Sex {sex}</p>

  <h2>Active problems</h2>{problems}
  <h2>Active medications</h2>{meds}
  <h2>Allergies</h2>{allergies}
  <h2>Recent vitals</h2>{vitals}
  <h2>Upcoming appointments</h2>{appts}

  <div class="print-hint"><button onclick="window.print()">Print / Save as PDF</button></div>
  <footer>MedAgent Health · This summary is generated from the patient's electronic record.
    Access to this document is recorded in the patient's access log (FR-5.8).</footer>
</body></html>"""


@router.get("/{phn}/summary/document")
async def patient_summary_document(
    phn: str,
    principal: Annotated[Principal, Depends(require_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[AsyncSession, Depends(get_session)],
    format: Annotated[str, Query(pattern="^(html|fhir)$")] = "html",
) -> Any:
    """Downloadable visit-summary export (FR-5.6, 07 §8).

    `format=html` (default): a self-contained printable document (browser → Save
    as PDF). `format=fhir`: the full FHIR `$everything` bundle for data portability
    (FR-6.4). Both are audited as an *export* against the patient (07 §10 shows
    "You exported your record"). Production adds a server-side PDF binary
    registered as a DocumentReference in object storage (03 §8.1)."""
    fhir = FHIRClient(settings.fhir_base_url)
    try:
        summary, pid = await _load_summary(fhir, phn)
        doc_id = f"VS-{uuid4().hex[:12].upper()}"
        generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        if format == "fhir":
            bundle = await fhir.everything("Patient", pid)
            payload: Any = JSONResponse(
                content=bundle,
                headers={"Content-Disposition": f'attachment; filename="record-{phn}.json"'},
                media_type="application/fhir+json",
            )
        else:
            doc = _render_summary_html(summary, doc_id=doc_id, generated=generated,
                                       actor=principal.subject)
            payload = HTMLResponse(content=doc)
    finally:
        await fhir.close()

    # Audit the export (07 §10 "You exported your record"). Opaque IDs only — no PHI
    # in the outbox payload. Dispatched to a FHIR AuditEvent by the outbox loop.
    session.add(AuditOutbox(event={
        "type": "record_exported",
        "actor": principal.subject,
        "patient_fhir_id": pid,
        "export_format": format,
        "document_id": doc_id,
    }))
    await session.commit()
    return payload

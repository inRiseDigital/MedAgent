"""Patient registration + demographic search (MPI v1, 02 §8, FR-2.4).

S1 skeleton: registration issues a PHN through the real MPI issuance path;
search is a SQL ILIKE skeleton over normalised fields. Probabilistic dedup
scoring and the FHIR Patient projection land later in S1/S2.
"""

from __future__ import annotations

import html
import logging
from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
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
    full = " ".join(name.get("given", []) + [name.get("family", "")]).strip()

    conditions = await fhir.search("Condition", {"patient": pid, "clinical-status": "active"})
    meds = await fhir.search("MedicationRequest", {"patient": pid, "status": "active"})
    allergies = await fhir.search("AllergyIntolerance", {"patient": pid})
    vitals = await fhir.search(
        "Observation", {"patient": pid, "category": "vital-signs", "_sort": "-date", "_count": "5"}
    )
    appts = await fhir.search("Appointment", {"patient": pid, "status": "booked", "_sort": "date"})

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

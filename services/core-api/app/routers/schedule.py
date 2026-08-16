"""Scheduling, waitlists & auto-booking (FR-9.5/9.6, 03 §3.6). Phase-2 backlog 5.2.

Everything is native FHIR scheduling:

  * `Slot`   — an available appointment slot (status free → busy), hung off a
    per-(facility, specialty) `Schedule` and tagged with the facility so it is one
    indexed `_tag` search.
  * `Appointment` — a waitlist entry is `status = waitlist` (a native status) with
    `priority` carrying the clinical urgency (1 asap → 3 routine). Auto-booking
    flips it to `status = booked`, stamps the slot's time, and marks the Slot busy.

Auto-booking is deterministic: waiting patients are ordered by urgency, then by how
long they have waited (FIFO within an urgency band), and matched to the earliest
free slots. The national waiting-time view aggregates the open waitlist per
facility/specialty.
"""

from __future__ import annotations

import logging
import statistics
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from redis.asyncio import Redis

from app.auth import Principal, require_user
from app.config import Settings
from app.deps import get_redis, get_session, get_settings
from app.events import publish_user
from app.fhir_client import FHIRClient
from app.models import AuditOutbox
from app.fhir.helpers import PHN_SYSTEM, resolve_pid as _resolve_pid

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/schedule", tags=["schedule"])

FACILITY_TAG = "https://fhir.medagent.health.lk/cs/schedule-facility"
SCHEDULE_ID = "https://fhir.medagent.health.lk/id/schedule"
_URGENCY = {"asap": 1, "urgent": 2, "routine": 3}
_URGENCY_LABEL = {1: "asap", 2: "urgent", 3: "routine"}


def _facility_of(res: dict[str, Any]) -> str | None:
    for tag in (res.get("meta") or {}).get("tag", []):
        if tag.get("system") == FACILITY_TAG:
            return tag.get("code")
    return None


def _specialty_of(res: dict[str, Any]) -> str | None:
    st = res.get("serviceType") or []
    return st[0].get("text") if st else None


async def _find_or_create_schedule(fhir: FHIRClient, facility: str, specialty: str, token: str | None) -> str:
    key = f"{facility}:{specialty}"
    rows = await fhir.search("Schedule", {"identifier": f"{SCHEDULE_ID}|{key}"})
    if rows:
        return str(rows[0]["id"])
    sch = await fhir.create("Schedule", {
        "resourceType": "Schedule", "active": True,
        "identifier": [{"system": SCHEDULE_ID, "value": key}],
        "serviceType": [{"text": specialty}],
        "meta": {"tag": [{"system": FACILITY_TAG, "code": facility}]},
        "comment": f"{specialty} @ {facility}",
    }, token)
    return str(sch["id"])


class SlotRequest(BaseModel):
    facility: str = Field(..., min_length=1)
    specialty: str = Field(..., min_length=1)
    slots: list[dict[str, str]] = Field(..., description="[{start,end}] ISO datetimes", min_length=1)


@router.post("/slots", status_code=status.HTTP_201_CREATED)
async def create_slots(
    body: SlotRequest,
    request: Request,
    principal: Annotated[Principal, Depends(require_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """Publish free slots for a facility/specialty (FR-9.5)."""
    auth = request.headers.get("authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else None
    fhir = FHIRClient(settings.fhir_base_url)
    try:
        sched_id = await _find_or_create_schedule(fhir, body.facility, body.specialty, token)
        created = []
        for s in body.slots:
            if not s.get("start") or not s.get("end"):
                raise HTTPException(status_code=422, detail="each slot needs start and end")
            r = await fhir.create("Slot", {
                "resourceType": "Slot", "status": "free",
                "schedule": {"reference": f"Schedule/{sched_id}"},
                "serviceType": [{"text": body.specialty}],
                "meta": {"tag": [{"system": FACILITY_TAG, "code": body.facility}]},
                "start": s["start"], "end": s["end"],
            }, token)
            created.append(f"Slot/{r.get('id')}")
        return {"schedule": f"Schedule/{sched_id}", "created": created, "count": len(created)}
    finally:
        await fhir.close()


class WaitlistRequest(BaseModel):
    patient: str = Field(..., description="PHN or FHIR id")
    facility: str = Field(..., min_length=1)
    specialty: str = Field(..., min_length=1)
    urgency: str = Field("routine", pattern="^(asap|urgent|routine)$")
    reason: str | None = None


@router.post("/waitlist", status_code=status.HTTP_201_CREATED)
async def add_to_waitlist(
    body: WaitlistRequest,
    request: Request,
    principal: Annotated[Principal, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """Add a patient to a facility/specialty waitlist (FR-9.6). Modelled as an
    Appointment with status=waitlist and priority = clinical urgency."""
    auth = request.headers.get("authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else None
    fhir = FHIRClient(settings.fhir_base_url)
    try:
        patient = await _resolve_pid(fhir, body.patient)
        if not patient:
            raise HTTPException(status_code=404, detail=f"no FHIR patient for {body.patient}")
        pid = str(patient["id"])
        now = datetime.now(timezone.utc).isoformat()
        appt = await fhir.create("Appointment", {
            "resourceType": "Appointment", "status": "waitlist",
            "priority": _URGENCY[body.urgency],
            "serviceType": [{"text": body.specialty}],
            "meta": {"tag": [{"system": FACILITY_TAG, "code": body.facility}]},
            "description": body.reason or f"{body.specialty} waitlist",
            "created": now,
            "participant": [{"actor": {"reference": f"Patient/{pid}"}, "status": "accepted"}],
        }, token)
        appt_id = str(appt["id"])
        session.add(AuditOutbox(event={
            "type": "waitlist_add", "actor": principal.subject, "patient_fhir_id": pid,
            "committed": f"Appointment/{appt_id}", "facility": body.facility,
            "specialty": body.specialty, "urgency": body.urgency,
        }))
        return {"appointment_id": appt_id, "status": "waitlist", "urgency": body.urgency}
    finally:
        await fhir.close()


def order_waitlist(waits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Booking order: urgency (priority asc = more urgent) then longest wait
    (created asc = FIFO within a band). Pure + testable."""
    return sorted(waits, key=lambda a: (a.get("priority", 3), a.get("created", "")))


def _patient_ref(appt: dict[str, Any]) -> str | None:
    for p in appt.get("participant", []):
        ref = (p.get("actor") or {}).get("reference", "")
        if ref.startswith("Patient/"):
            return ref
    return None


@router.post("/auto-book")
async def auto_book(
    request: Request,
    principal: Annotated[Principal, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    facility: Annotated[str, Query(min_length=1)],
    specialty: Annotated[str, Query(min_length=1)],
) -> dict[str, Any]:
    """Assign waiting patients to free slots, ordered by urgency then wait time
    (FR-9.6). Deterministic; returns the bookings made."""
    auth = request.headers.get("authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else None
    fhir = FHIRClient(settings.fhir_base_url)
    try:
        slots = [
            s for s in await fhir.search("Slot", {"_tag": f"{FACILITY_TAG}|{facility}",
                                                  "status": "free", "_count": "200"})
            if _specialty_of(s) == specialty and s.get("start")
        ]
        slots.sort(key=lambda s: s["start"])  # earliest first
        waits = [
            a for a in await fhir.search("Appointment", {"_tag": f"{FACILITY_TAG}|{facility}",
                                                         "status": "waitlist", "_count": "200"})
            if _specialty_of(a) == specialty
        ]
        waits = order_waitlist(waits)  # urgency, then longest wait (FIFO within band)

        booked = []
        for appt in waits:
            if not slots:
                break
            slot = slots.pop(0)
            appt["status"] = "booked"
            appt["start"], appt["end"] = slot["start"], slot["end"]
            appt["slot"] = [{"reference": f"Slot/{slot['id']}"}]
            await fhir.update("Appointment", str(appt["id"]), appt, token)
            slot["status"] = "busy"
            await fhir.update("Slot", str(slot["id"]), slot, token)
            pid = (_patient_ref(appt) or "").split("/", 1)[-1] or None
            session.add(AuditOutbox(event={
                "type": "appointment_booked", "actor": principal.subject, "patient_fhir_id": pid,
                "committed": f"Appointment/{appt['id']}", "facility": facility,
                "specialty": specialty, "start": slot["start"],
                "urgency": _URGENCY_LABEL.get(appt.get("priority", 3), "routine"),
            }))
            booked.append({"appointment_id": str(appt["id"]), "patient": _patient_ref(appt),
                           "start": slot["start"], "urgency": _URGENCY_LABEL.get(appt.get("priority", 3), "routine")})
        return {"facility": facility, "specialty": specialty,
                "booked": booked, "remaining_waitlist": len(waits) - len(booked),
                "free_slots_left": len(slots)}
    finally:
        await fhir.close()


@router.get("/slots")
async def list_free_slots(
    principal: Annotated[Principal, Depends(require_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    facility: str | None = None,
    specialty: str | None = None,
) -> dict[str, Any]:
    """Free slots a patient can book, earliest first (FR-9.5, patient self-service)."""
    fhir = FHIRClient(settings.fhir_base_url)
    try:
        params: dict[str, str] = {"status": "free", "_count": "100"}
        if facility:
            params["_tag"] = f"{FACILITY_TAG}|{facility}"
        rows = await fhir.search("Slot", params)
        out = []
        for s in rows:
            if not s.get("start"):
                continue
            spec = _specialty_of(s)
            if specialty and spec != specialty:
                continue
            out.append({
                "id": f"Slot/{s['id']}", "start": s.get("start"), "end": s.get("end"),
                "facility": _facility_of(s), "specialty": spec,
            })
        out.sort(key=lambda x: x["start"] or "")
        return {"slots": out[:60]}
    finally:
        await fhir.close()


class BookRequest(BaseModel):
    slot: str = Field(..., description="Slot/<id> or <id>")
    patient: str = Field(..., description="PHN or FHIR id")
    reason: str | None = None


@router.post("/book", status_code=status.HTTP_201_CREATED)
async def book_slot(
    body: BookRequest,
    request: Request,
    principal: Annotated[Principal, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> dict[str, Any]:
    """Patient self-service booking: claim a specific free Slot and create a booked
    FHIR Appointment. Fail-closed if the slot was taken (409)."""
    auth = request.headers.get("authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else None
    slot_id = body.slot.split("/", 1)[-1]
    fhir = FHIRClient(settings.fhir_base_url)
    try:
        patient = await _resolve_pid(fhir, body.patient)
        if not patient:
            raise HTTPException(status_code=404, detail=f"no FHIR patient for {body.patient}")
        pid = str(patient["id"])
        try:
            slot = await fhir.read("Slot", slot_id)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=404, detail=f"no slot {slot_id}") from exc
        if slot.get("status") != "free":
            raise HTTPException(status_code=409, detail="that slot is no longer available")
        facility = _facility_of(slot)
        specialty = _specialty_of(slot)
        appt = await fhir.create("Appointment", {
            "resourceType": "Appointment", "status": "booked",
            "serviceType": [{"text": specialty}] if specialty else [],
            "meta": {"tag": [{"system": FACILITY_TAG, "code": facility}]} if facility else {},
            "description": body.reason or (f"{specialty} appointment" if specialty else "Appointment"),
            "start": slot.get("start"), "end": slot.get("end"),
            "slot": [{"reference": f"Slot/{slot_id}"}],
            "participant": [{"actor": {"reference": f"Patient/{pid}"}, "status": "accepted"}],
        }, token)
        slot["status"] = "busy"
        await fhir.update("Slot", slot_id, slot, token)
        appt_id = str(appt["id"])
        session.add(AuditOutbox(event={
            "type": "appointment_booked", "actor": principal.subject, "patient_fhir_id": pid,
            "committed": f"Appointment/{appt_id}", "facility": facility,
            "specialty": specialty, "start": slot.get("start"), "self_service": True,
        }))
        try:
            await publish_user(redis, principal.subject, {
                "type": "appointment_booked", "title": "Appointment confirmed",
                "body": f"{specialty or 'Your appointment'} — {slot.get('start', '')[:16].replace('T', ' ')}",
                "ref": f"Appointment/{appt_id}",
            })
        except Exception:  # noqa: BLE001 — notification is best-effort, never fails the booking
            logger.warning("failed to publish booking notification", exc_info=True)
        return {"appointment_id": appt_id, "status": "booked", "start": slot.get("start"),
                "end": slot.get("end"), "facility": facility, "specialty": specialty}
    finally:
        await fhir.close()


@router.get("/waiting-times")
async def waiting_times(
    principal: Annotated[Principal, Depends(require_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    facility: str | None = None,
) -> dict[str, Any]:
    """National (or per-facility) waiting-time view (FR-9.6): open waitlist grouped
    by facility/specialty with wait-day stats and the next free slot."""
    fhir = FHIRClient(settings.fhir_base_url)
    try:
        appt_params = {"status": "waitlist", "_count": "500"}
        if facility:
            appt_params["_tag"] = f"{FACILITY_TAG}|{facility}"
        waits = await fhir.search("Appointment", appt_params)
        slot_params = {"status": "free", "_count": "500"}
        if facility:
            slot_params["_tag"] = f"{FACILITY_TAG}|{facility}"
        free_slots = await fhir.search("Slot", slot_params)

        now = datetime.now(timezone.utc)
        groups: dict[tuple[str, str], list[float]] = {}
        for a in waits:
            fac, spec = _facility_of(a) or "?", _specialty_of(a) or "?"
            created = a.get("created")
            days = 0.0
            if created:
                try:
                    days = (now - datetime.fromisoformat(created.replace("Z", "+00:00"))).total_seconds() / 86400
                except ValueError:
                    days = 0.0
            groups.setdefault((fac, spec), []).append(round(days, 2))

        next_free: dict[tuple[str, str], str] = {}
        for s in free_slots:
            fac, spec = _facility_of(s) or "?", _specialty_of(s) or "?"
            st = s.get("start")
            if st and (next_free.get((fac, spec)) is None or st < next_free[(fac, spec)]):
                next_free[(fac, spec)] = st

        rows = []
        for (fac, spec), ds in sorted(groups.items()):
            rows.append({
                "facility": fac, "specialty": spec, "waiting": len(ds),
                "median_wait_days": round(statistics.median(ds), 2) if ds else 0,
                "max_wait_days": max(ds) if ds else 0,
                "next_free_slot": next_free.get((fac, spec)),
            })
        return {"as_of": now.isoformat(), "groups": rows}
    finally:
        await fhir.close()

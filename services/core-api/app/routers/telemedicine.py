"""Telemedicine e-consults with guardian/family join (FR-9.7, 03 §3.6). Backlog 5.3.

A virtual consult is a FHIR `Appointment` (appointmentType = virtual) that provisions
a video room and issues one **single-use** join token per participant — the patient,
the clinician, and any guardians linked via `RelatedPerson` (the birth-enrolment
proxy from 4.1). Tokens live in Redis and are redeemed with `GETDEL`, so a link
works exactly once (the SSE-ticket pattern, 02 §11).

Lifecycle: on start we open an `Encounter` (class=virtual, in-progress); on complete
we finish it. The post-consult e-Rx reuses the ordinary screened prescription path
(`POST /proposals/commit`, kind=prescription) referencing that Encounter — a
tele-consult prescription is safety-screened exactly like an in-person one.
"""

from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import Principal, require_user
from app.config import Settings
from app.deps import get_redis, get_session, get_settings
from app.fhir_client import FHIRClient
from app.fhir.helpers import PHN_SYSTEM, resolve_pid as _resolve_pid
from app.models import AuditOutbox

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/telemedicine", tags=["telemedicine"])

VIRTUAL = "http://terminology.hl7.org/CodeSystem/v3-ActCode"  # code VR = virtual
# Namespaced under `core:` to fit core-api's least-privilege Redis ACL grant
# (infra/compose/redis/users.acl: core-api may access ~core:*).
_JOIN_KEY = "core:tele:join:{token}"




def _display(res: dict[str, Any]) -> str:
    name = next((n for n in res.get("name", [])), {})
    return name.get("text") or " ".join(name.get("given", []) + [name.get("family", "")]).strip() or "Unknown"


class SessionRequest(BaseModel):
    patient: str = Field(..., description="PHN or FHIR id")
    reason: str = Field(..., min_length=1)
    scheduled_start: str | None = None  # ISO; defaults to now


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
async def create_session(
    body: SessionRequest,
    request: Request,
    principal: Annotated[Principal, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> dict[str, Any]:
    """Provision a video e-consult and issue single-use join tokens for the patient,
    the clinician, and every linked guardian (FR-9.7)."""
    auth = request.headers.get("authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else None
    fhir = FHIRClient(settings.fhir_base_url)
    try:
        patient = await _resolve_pid(fhir, body.patient)
        if not patient:
            raise HTTPException(status_code=404, detail=f"no FHIR patient for {body.patient}")
        pid = str(patient["id"])
        start = body.scheduled_start or datetime.now(timezone.utc).isoformat()
        room_id = secrets.token_urlsafe(9)

        appt = await fhir.create("Appointment", {
            "resourceType": "Appointment", "status": "booked",
            "appointmentType": {"coding": [{"system": VIRTUAL, "code": "VR", "display": "virtual"}]},
            "serviceType": [{"text": body.reason}],
            "description": body.reason, "start": start,
            "participant": [{"actor": {"reference": f"Patient/{pid}"}, "status": "accepted"}],
        }, token)
        sid = str(appt["id"])

        # Participants: patient + clinician + guardians (RelatedPerson proxies).
        participants: list[dict[str, str]] = [
            {"role": "patient", "display": _display(patient), "ref": f"Patient/{pid}"},
            {"role": "clinician", "display": principal.subject, "ref": principal.subject},
        ]
        guardians = await fhir.search("RelatedPerson", {"patient": pid})
        for g in guardians:
            participants.append({"role": "guardian", "display": _display(g),
                                 "ref": f"RelatedPerson/{g.get('id')}"})

        join = []
        for p in participants:
            jt = secrets.token_urlsafe(24)
            await redis.set(
                _JOIN_KEY.format(token=jt),
                json.dumps({"session_id": sid, "room_id": room_id, "role": p["role"],
                            "display": p["display"], "participant_ref": p["ref"], "patient_ref": f"Patient/{pid}"}),
                ex=settings.telemedicine_join_ttl_seconds,
            )
            join.append({"role": p["role"], "display": p["display"], "token": jt,
                         "link": f"https://video.medagent.health.lk/room/{room_id}?t={jt}"})

        session.add(AuditOutbox(event={
            "type": "econsult_created", "actor": principal.subject, "patient_fhir_id": pid,
            "committed": f"Appointment/{sid}", "participants": len(join),
        }))
        return {"session_id": sid, "room_id": room_id, "status": "booked", "start": start, "join": join}
    finally:
        await fhir.close()


@router.get("/sessions/{sid}/join")
async def join_session(
    sid: str,
    principal: Annotated[Principal, Depends(require_user)],
    redis: Annotated[Redis, Depends(get_redis)],
    token: Annotated[str, Query(min_length=8, description="Single-use join token")],
) -> dict[str, Any]:
    """Redeem a single-use join token (GETDEL) and return the room credentials.
    Reused/expired tokens 401; a guardian's token joins as family (FR-9.7)."""
    raw = await redis.getdel(_JOIN_KEY.format(token=token))
    if not raw:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="invalid, already-used, or expired join token")
    data = json.loads(raw)
    if data.get("session_id") != sid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="token is for a different session")
    return {"session_id": sid, "room_id": data["room_id"], "role": data["role"],
            "display": data["display"], "patient_ref": data["patient_ref"],
            # Signalling stub — a real deployment returns SFU/ICE credentials here.
            "media": {"provider": "medagent-sfu", "room": data["room_id"]}}


async def _load_appt(fhir: FHIRClient, sid: str) -> dict[str, Any]:
    try:
        return await fhir.read("Appointment", sid)
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=404, detail="session not found")


@router.post("/sessions/{sid}/start")
async def start_session(
    sid: str,
    request: Request,
    principal: Annotated[Principal, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """Begin the consult: mark the Appointment checked-in and open a virtual
    Encounter (in-progress). Returns the encounter id to reference on the e-Rx."""
    auth = request.headers.get("authorization", "")
    tok = auth[7:] if auth.lower().startswith("bearer ") else None
    fhir = FHIRClient(settings.fhir_base_url)
    try:
        appt = await _load_appt(fhir, sid)
        if appt.get("status") not in ("booked", "arrived"):
            raise HTTPException(status_code=409, detail=f"cannot start a session in state '{appt.get('status')}'")
        pref = next((p.get("actor", {}).get("reference") for p in appt.get("participant", [])
                     if p.get("actor", {}).get("reference", "").startswith("Patient/")), None)
        appt["status"] = "checked-in"
        await fhir.update("Appointment", sid, appt, tok)
        enc = await fhir.create("Encounter", {
            "resourceType": "Encounter", "status": "in-progress",
            "class": {"system": VIRTUAL, "code": "VR", "display": "virtual"},
            "subject": {"reference": pref} if pref else None,
            "appointment": [{"reference": f"Appointment/{sid}"}],
            "period": {"start": datetime.now(timezone.utc).isoformat()},
        }, tok)
        enc_id = str(enc["id"])
        pid = (pref or "").split("/", 1)[-1] or None
        session.add(AuditOutbox(event={
            "type": "econsult_started", "actor": principal.subject, "patient_fhir_id": pid,
            "committed": f"Encounter/{enc_id}",
        }))
        return {"session_id": sid, "status": "in-progress", "encounter_id": enc_id}
    finally:
        await fhir.close()


@router.post("/sessions/{sid}/complete")
async def complete_session(
    sid: str,
    request: Request,
    principal: Annotated[Principal, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    encounter_id: Annotated[str | None, Query()] = None,
) -> dict[str, Any]:
    """End the consult: finish the Encounter and mark the Appointment fulfilled.
    After this the e-Rx can be issued via the normal screened prescription path
    (POST /proposals/commit, kind=prescription) referencing encounter_id."""
    auth = request.headers.get("authorization", "")
    tok = auth[7:] if auth.lower().startswith("bearer ") else None
    fhir = FHIRClient(settings.fhir_base_url)
    try:
        appt = await _load_appt(fhir, sid)
        if appt.get("status") != "checked-in":
            raise HTTPException(status_code=409, detail=f"cannot complete a session in state '{appt.get('status')}'")
        appt["status"] = "fulfilled"
        await fhir.update("Appointment", sid, appt, tok)
        if encounter_id:
            try:
                enc = await fhir.read("Encounter", encounter_id)
                enc["status"] = "finished"
                enc.setdefault("period", {})["end"] = datetime.now(timezone.utc).isoformat()
                await fhir.update("Encounter", encounter_id, enc, tok)
            except HTTPException:
                raise
            except Exception:  # noqa: BLE001
                logger.warning("could not finish encounter %s", encounter_id)
        pref = next((p.get("actor", {}).get("reference") for p in appt.get("participant", [])
                     if p.get("actor", {}).get("reference", "").startswith("Patient/")), None)
        pid = (pref or "").split("/", 1)[-1] or None
        session.add(AuditOutbox(event={
            "type": "econsult_completed", "actor": principal.subject, "patient_fhir_id": pid,
            "committed": f"Appointment/{sid}",
        }))
        return {"session_id": sid, "status": "fulfilled",
                "eprescription": {"path": "/api/v1/proposals/commit", "kind": "prescription",
                                  "encounter_id": encounter_id}}
    finally:
        await fhir.close()

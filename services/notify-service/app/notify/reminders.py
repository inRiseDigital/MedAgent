"""Appointment reminder scan (FR-15.1, FR-5.4, agents/08).

Scans FHIR for upcoming booked appointments and sends a reminder per patient,
deduping via a Redis set so a patient is reminded once per appointment. No LLM:
scheduling is deterministic (message templating in the patient's language is a
Phase-B refinement). Respects quiet hours unless forced.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.notify.dispatch import dispatch

logger = logging.getLogger(__name__)

REMINDED_SET = "notify:reminded"


def _in_quiet_hours(hour: int, start: int, end: int) -> bool:
    # Quiet window wraps midnight (e.g. 20:00–08:00).
    return hour >= start or hour < end if start > end else start <= hour < end


async def _patient_contact(client: httpx.AsyncClient, base: str, ref: str) -> tuple[str, str | None]:
    """Return (email, phone) for a Patient reference, with a demo email fallback."""
    pid = ref.split("/")[-1]
    email = f"patient-{pid}@demo.medagent.local"
    phone = None
    try:
        resp = await client.get(f"{base}/{ref}", headers={"Accept": "application/fhir+json"})
        if resp.status_code == 200:
            for t in resp.json().get("telecom", []):
                if t.get("system") == "email" and t.get("value"):
                    email = t["value"]
                elif t.get("system") == "phone" and t.get("value"):
                    phone = t["value"]
    except httpx.HTTPError:
        pass
    return email, phone


async def run_reminders(settings: Any, app_state: Any, force: bool = False) -> dict[str, int]:
    now = datetime.now(timezone.utc)
    if not force and _in_quiet_hours(
        now.hour, settings.reminder_quiet_start_hour, settings.reminder_quiet_end_hour
    ):
        logger.info("reminders skipped (quiet hours)")
        return {"scanned": 0, "sent": 0, "skipped_quiet": 1}

    base = settings.fhir_base_url.rstrip("/")
    redis = app_state.redis
    sent = scanned = 0
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{base}/Appointment",
            params={"status": "booked", "_count": "100"},
            headers={"Accept": "application/fhir+json"},
        )
        resp.raise_for_status()
        appts = [e["resource"] for e in resp.json().get("entry", []) if "resource" in e]

        for appt in appts:
            scanned += 1
            aid = appt.get("id")
            start = appt.get("start")
            if not aid or not start:
                continue
            try:
                start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
            except ValueError:
                continue
            days_ahead = (start_dt - now).days
            if days_ahead < 0 or days_ahead > settings.reminder_lookahead_days:
                continue
            if await redis.sismember(REMINDED_SET, aid):
                continue
            patient_ref = next(
                (p["actor"]["reference"] for p in appt.get("participant", [])
                 if p.get("actor", {}).get("reference", "").startswith("Patient/")),
                None,
            )
            if not patient_ref:
                continue
            email, phone = await _patient_contact(client, base, patient_ref)
            subject = "Appointment reminder"
            body = f"You have an appointment on {start_dt.date().isoformat()}. Reply or call to reschedule."
            await dispatch(app_state, "email", email, subject, body)
            if phone:
                await dispatch(app_state, "sms", phone, subject, body)
            await redis.sadd(REMINDED_SET, aid)
            sent += 1

    logger.info("reminder scan complete", extra={"scanned": scanned, "sent": sent})
    return {"scanned": scanned, "sent": sent, "skipped_quiet": 0}

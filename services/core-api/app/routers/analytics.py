"""National analytics & early-warning (FR-12, 03 §3.9). Phase-2 backlog 6.3.

Deterministic aggregation over the data the platform already produces — notifiable
cases (registry Flags), lab/imaging reports, referrals, and the scheduling
waitlist. Three read-only views:

  * `/analytics/overview`  — national KPI snapshot.
  * `/analytics/outbreak`  — notifiable-disease early-warning: case counts vs a
    curated per-disease threshold → signal (none / watch / alert).
  * `/analytics/capacity`  — waitlist depth, free slots, and open referrals.

Thresholds are a clinician-owned ruleset, not a model output — the same
deterministic-first stance as the rest of the platform.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import Principal, require_user
from app.config import Settings
from app.deps import get_session, get_settings
from app.fhir_client import FHIRClient
from app.models import PatientMPI
from app.routers.referrals import REFERRAL_FACILITY_SYSTEM
from app.routers.registry import DISEASE_TAG, REGISTRY_TAG
from app.routers.schedule import FACILITY_TAG

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/analytics", tags=["analytics"])

# Curated outbreak thresholds: disease -> (watch, alert) case counts in view.
# Low-incidence/elimination-target diseases trip at a single case.
_OUTBREAK: dict[str, tuple[int, int]] = {
    "dengue": (3, 8), "malaria": (1, 3), "measles": (1, 2), "cholera": (1, 1),
    "leptospirosis": (3, 8), "rabies": (1, 1), "diphtheria": (1, 1),
}
_DEFAULT_THRESHOLD = (5, 15)


async def _count(fhir: FHIRClient, rtype: str, params: dict[str, str] | None = None) -> int:
    try:
        resp = await fhir._get(f"/{rtype}", params={"_summary": "count", **(params or {})}, token=None)
        return int(resp.json().get("total") or 0)
    except Exception:  # noqa: BLE001
        return 0


async def _notifiable_counts(fhir: FHIRClient) -> Counter[str]:
    flags = await fhir.search("Flag", {"_tag": f"{REGISTRY_TAG}|notifiable", "_count": "1000"})
    counts: Counter[str] = Counter()
    for f in flags:
        key = next((c.get("code") for c in (f.get("code") or {}).get("coding", [])
                    if c.get("system") == DISEASE_TAG), None)
        if key:
            counts[key] += 1
    return counts


@router.get("/overview")
async def overview(
    principal: Annotated[Principal, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """National KPI snapshot (FR-12.1)."""
    fhir = FHIRClient(settings.fhir_base_url)
    try:
        mpi_total = (await session.execute(select(func.count()).select_from(PatientMPI))).scalar() or 0
        notifiable = await _notifiable_counts(fhir)
        return {
            "as_of": datetime.now(timezone.utc).isoformat(),
            "patients_registered": int(mpi_total),
            "lab_reports": await _count(fhir, "DiagnosticReport"),
            "imaging_studies": await _count(fhir, "ImagingStudy"),
            "immunizations": await _count(fhir, "Immunization"),
            "referrals_open": await _count(fhir, "Task", {"status": "requested"}),
            "appointments": await _count(fhir, "Appointment"),
            "notifiable_cases": sum(notifiable.values()),
            "notifiable_by_disease": dict(sorted(notifiable.items())),
        }
    finally:
        await fhir.close()


@router.get("/outbreak")
async def outbreak(
    principal: Annotated[Principal, Depends(require_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """Notifiable-disease early-warning (FR-12.2): case counts vs curated
    thresholds → per-disease signal, most-severe first."""
    fhir = FHIRClient(settings.fhir_base_url)
    try:
        counts = await _notifiable_counts(fhir)
        signals = []
        for disease, n in counts.items():
            watch, alert = _OUTBREAK.get(disease, _DEFAULT_THRESHOLD)
            level = "alert" if n >= alert else "watch" if n >= watch else "none"
            signals.append({"disease": disease, "cases": n, "watch_at": watch,
                            "alert_at": alert, "signal": level})
        rank = {"alert": 0, "watch": 1, "none": 2}
        signals.sort(key=lambda s: (rank[s["signal"]], -s["cases"]))
        return {"as_of": datetime.now(timezone.utc).isoformat(),
                "any_alert": any(s["signal"] == "alert" for s in signals),
                "signals": signals}
    finally:
        await fhir.close()


@router.get("/capacity")
async def capacity(
    principal: Annotated[Principal, Depends(require_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    facility: str | None = None,
) -> dict[str, Any]:
    """Capacity view (FR-12.3): waitlist depth, free slots, open referrals — by
    facility."""
    fhir = FHIRClient(settings.fhir_base_url)
    try:
        appt_params = {"status": "waitlist", "_count": "500"}
        slot_params = {"status": "free", "_count": "500"}
        ref_params = {"status": "requested", "_count": "500"}
        if facility:
            appt_params["_tag"] = slot_params["_tag"] = f"{FACILITY_TAG}|{facility}"
            ref_params["_tag"] = f"{REFERRAL_FACILITY_SYSTEM}|{facility}"
        waits = await fhir.search("Appointment", appt_params)
        slots = await fhir.search("Slot", slot_params)
        refs = await fhir.search("Task", ref_params)

        def _fac(res: dict[str, Any], system: str) -> str:
            for t in (res.get("meta") or {}).get("tag", []):
                if t.get("system") == system:
                    return t.get("code")
            return "?"

        waitlist_by_fac: Counter[str] = Counter(_fac(a, FACILITY_TAG) for a in waits)
        free_by_fac: Counter[str] = Counter(_fac(s, FACILITY_TAG) for s in slots)
        refs_by_fac: Counter[str] = Counter(_fac(r, REFERRAL_FACILITY_SYSTEM) for r in refs)
        facilities = sorted(set(waitlist_by_fac) | set(free_by_fac) | set(refs_by_fac))
        rows = [{"facility": f, "waitlist": waitlist_by_fac.get(f, 0),
                 "free_slots": free_by_fac.get(f, 0), "open_referrals": refs_by_fac.get(f, 0)}
                for f in facilities]
        return {"as_of": datetime.now(timezone.utc).isoformat(),
                "totals": {"waitlist": len(waits), "free_slots": len(slots), "open_referrals": len(refs)},
                "by_facility": rows}
    finally:
        await fhir.close()

"""Paediatric clinical logic: EPI immunization schedule + WHO growth standards
(FR-7.3/7.4/7.5). Extracted from routers/patients.py (P3.3) so the clinical
knowledge tables and the deterministic assessment functions live in one testable
place, separate from the HTTP endpoints that call them.

Pure functions (they take a FHIRClient + resolved patient dict); no FastAPI here.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.fhir_client import FHIRClient

# --- Immunization (EPI) -----------------------------------------------------
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


async def _compute_immunizations(fhir: FHIRClient, patient: dict[str, Any]) -> dict[str, Any]:
    """Immunization schedule + status for a resolved patient (shared by the
    immunizations endpoint and the CHDR aggregate)."""
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


# --- Growth monitoring (FR-7.4/7.5, backlog 4.3) ----------------------------
# WHO child growth standards, curated pilot subset. Weight-for-age and
# length/height-for-age -2SD cutoffs (kg / cm) by age-months, per sex; a value
# below the -2SD line flags underweight / stunting. Linear-interpolated between
# table ages. (Wasting = weight-for-height extends this the same way.)
WEIGHT_LOINC, HEIGHT_LOINC = "29463-7", "8302-2"
_WFA_NEG2 = {  # weight-for-age -2SD (kg)
    "male": {0: 2.5, 1: 3.4, 2: 4.4, 3: 5.1, 6: 6.4, 9: 7.1, 12: 7.7, 18: 8.8, 24: 9.7},
    "female": {0: 2.4, 1: 3.2, 2: 3.9, 3: 4.5, 6: 5.7, 9: 6.5, 12: 7.0, 18: 8.1, 24: 8.9},
}
_LFA_NEG2 = {  # length/height-for-age -2SD (cm)
    "male": {0: 46.1, 6: 63.3, 12: 71.0, 18: 76.9, 24: 81.7},
    "female": {0: 45.4, 6: 61.2, 12: 68.9, 18: 74.9, 24: 80.0},
}


def _interp(table: dict[int, float], age_m: float) -> float | None:
    ks = sorted(table)
    if not ks:
        return None
    if age_m <= ks[0]:
        return table[ks[0]]
    if age_m >= ks[-1]:
        return table[ks[-1]]
    for a, b in zip(ks, ks[1:]):
        if a <= age_m <= b:
            return table[a] + (table[b] - table[a]) * (age_m - a) / (b - a)
    return None


def _sex_key(gender: str | None) -> str:
    return "male" if gender == "male" else "female"  # default female (more sensitive)


def _assess_growth(gender: str | None, age_m: float | None, weight: float | None,
                   height: float | None) -> list[str]:
    if age_m is None:
        return []
    sk = _sex_key(gender)
    flags: list[str] = []
    w2 = _interp(_WFA_NEG2[sk], age_m)
    if weight is not None and w2 is not None and weight < w2:
        flags.append("underweight")
    l2 = _interp(_LFA_NEG2[sk], age_m)
    if height is not None and l2 is not None and height < l2:
        flags.append("stunted")
    return flags


def _age_months(birth: date | None, when: date) -> float | None:
    return round((when - birth).days / 30.4375, 2) if birth else None


async def _compute_growth(fhir: FHIRClient, patient: dict[str, Any]) -> dict[str, Any]:
    """Growth history + latest WHO flags for a resolved patient (shared by the
    growth endpoint and the CHDR aggregate)."""
    pid = str(patient["id"])
    gender = patient.get("gender")
    bd = date.fromisoformat(patient["birthDate"]) if patient.get("birthDate") else None
    obs = await fhir.search("Observation",
                            {"patient": pid, "category": "vital-signs", "_sort": "-date", "_count": "100"})
    points: list[dict[str, Any]] = []
    latest_w: tuple[str, float] | None = None
    latest_h: tuple[str, float] | None = None
    for o in obs:
        loinc = next((c.get("code") for c in (o.get("code") or {}).get("coding", [])
                      if c.get("system") == "http://loinc.org"), None)
        if loinc not in (WEIGHT_LOINC, HEIGHT_LOINC):
            continue
        when = o.get("effectiveDateTime", "")[:10]
        val = (o.get("valueQuantity") or {}).get("value")
        if not when or val is None:
            continue
        age_m = _age_months(bd, date.fromisoformat(when))
        kind = "weight" if loinc == WEIGHT_LOINC else "height"
        flags = _assess_growth(gender, age_m, val if kind == "weight" else None,
                               val if kind == "height" else None)
        points.append({"date": when, "age_months": age_m, "kind": kind, "value": val, "flags": flags})
        if kind == "weight" and (latest_w is None or when > latest_w[0]):
            latest_w = (when, val)
        if kind == "height" and (latest_h is None or when > latest_h[0]):
            latest_h = (when, val)
    latest_flags = _assess_growth(
        gender,
        _age_months(bd, date.fromisoformat(latest_w[0])) if latest_w else (
            _age_months(bd, date.fromisoformat(latest_h[0])) if latest_h else None),
        latest_w[1] if latest_w else None, latest_h[1] if latest_h else None,
    )
    return {"points": points, "latest_flags": latest_flags}

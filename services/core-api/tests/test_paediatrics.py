"""Regression tests for the paediatric clinical logic (P3.3/P6).

These lock down the deterministic WHO growth assessment and EPI schedule maths
that were extracted from patients.py into app/clinical/paediatrics.py. Pure
functions — no FHIR, no DB — except the two compute_* helpers which take a tiny
fake FHIR client.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.clinical import paediatrics as p


# --- immunization schedule maths --------------------------------------------
def test_add_months_basic_and_year_rollover() -> None:
    assert p._add_months(date(2020, 1, 15), 2) == date(2020, 3, 15)
    assert p._add_months(date(2020, 11, 10), 4) == date(2021, 3, 10)  # crosses year


def test_add_months_clamps_short_month() -> None:
    # Jan 31 + 1 month has no Feb 31 → clamp to the last valid day (2020 is leap).
    assert p._add_months(date(2020, 1, 31), 1) == date(2020, 2, 29)
    assert p._add_months(date(2021, 1, 31), 1) == date(2021, 2, 28)


# --- WHO growth interpolation + assessment ----------------------------------
def test_interp_midpoint_and_clamping() -> None:
    table = {0: 2.5, 12: 7.7}
    assert p._interp(table, 6) == 5.1  # linear midpoint
    assert p._interp(table, -5) == 2.5  # clamp below first key
    assert p._interp(table, 99) == 7.7  # clamp above last key
    assert p._interp({}, 6) is None


def test_sex_key_defaults_to_female() -> None:
    assert p._sex_key("male") == "male"
    assert p._sex_key("female") == "female"
    assert p._sex_key(None) == "female"  # more-sensitive default


def test_assess_growth_flags() -> None:
    # A 12-month-old male: WFA -2SD = 7.7 kg, LFA -2SD = 71.0 cm.
    assert p._assess_growth("male", 12, 6.0, 80.0) == ["underweight"]
    assert p._assess_growth("male", 12, 9.0, 65.0) == ["stunted"]
    assert set(p._assess_growth("male", 12, 6.0, 65.0)) == {"underweight", "stunted"}
    assert p._assess_growth("male", 12, 9.0, 80.0) == []  # healthy
    assert p._assess_growth("male", None, 1.0, 1.0) == []  # no age → no assessment


def test_age_months() -> None:
    assert p._age_months(None, date(2024, 1, 1)) is None
    am = p._age_months(date(2023, 1, 1), date(2024, 1, 1))
    assert am is not None and 11.9 < am < 12.1


# --- compute_immunizations against a fake FHIR ------------------------------
class _FakeFhir:
    def __init__(self, immunizations: list[dict[str, Any]]) -> None:
        self._imm = immunizations

    async def search(self, resource_type: str, _params: dict[str, str]) -> list[dict[str, Any]]:
        return self._imm if resource_type == "Immunization" else []


async def test_compute_immunizations_statuses() -> None:
    # Newborn today: BCG (0m) is due now/soon, later doses upcoming; nothing overdue.
    patient = {"id": "123", "birthDate": date.today().isoformat()}
    given = [{"identifier": [{"system": p.IMMUNIZATION_KEY_SYSTEM, "value": "bcg"}],
              "occurrenceDateTime": date.today().isoformat()}]
    out = await p._compute_immunizations(_FakeFhir(given), patient)
    by_key = {r["key"]: r for r in out["schedule"]}
    assert by_key["bcg"]["status"] == "given"
    assert out["overdue"] == 0
    assert by_key["dtp_booster"]["status"] == "upcoming"  # due at 18m, far off

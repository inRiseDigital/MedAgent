"""Tests for the grounded-context builder (P1.1)."""

from __future__ import annotations

from app.agent.context import _dedup, _fmt_date, _num, _render, build_patient_context

_SUMMARY = {
    "patient": {"phn": "55246820131", "name": "Nimal Perera", "gender": "male", "birthDate": "1985-03-12"},
    "problems": [{"text": "Type 2 diabetes", "ref": "Condition/1"}],
    "medications": [{"text": "Metformin", "ref": "MedicationRequest/2"}],
    "allergies": [{"text": "Penicillin", "criticality": "high", "ref": "AllergyIntolerance/3"}],
    "vitals": [{"text": "Heart rate", "value": 78, "unit": "/min"}],
    "results": [{"text": "Serum potassium", "critical": True, "ref": "DiagnosticReport/4"}],
}
_BRIEF = {"flags": [{"text": "High-risk allergy: Penicillin", "cite": "AllergyIntolerance/3"}]}


def test_render_produces_cited_context() -> None:
    out = _render(_SUMMARY, _BRIEF)
    assert "CURRENT PATIENT CONTEXT" in out
    assert "Nimal Perera" in out
    assert "[source: Condition/1]" in out  # citations carried through
    assert "[source: MedicationRequest/2]" in out
    assert "SAFETY FLAGS" in out and "AllergyIntolerance/3" in out
    assert "(CRITICAL)" in out  # critical result flagged


def test_render_tolerates_empty_brief() -> None:
    out = _render(_SUMMARY, None)
    assert "Nimal Perera" in out
    assert "SAFETY FLAGS" not in out  # no brief → no flags line, but no crash


def test_fmt_date_is_human_readable() -> None:
    # Raw microsecond ISO timestamps must render as a legible date/time, not a machine string.
    assert _fmt_date("2026-07-27T11:41:23.738939+00:00", with_time=True) == "27 Jul 2026, 11:41"
    assert _fmt_date("2026-07-20") == "20 Jul 2026"
    assert _fmt_date("not-a-date") == "not-a-date"  # malformed → raw, never dropped
    assert _fmt_date(None) == ""


def test_num_drops_noise_trailing_zeros() -> None:
    assert _num(6.0) == "6"
    assert _num(6.4) == "6.4"
    assert _num(61.0) == "61"
    assert _num(None) == ""


def test_dedup_collapses_identical_displays() -> None:
    rows = [{"text": "Paracetamol"}, {"text": "paracetamol"}, {"text": "Aspirin"}]
    assert [r["text"] for r in _dedup(rows, lambda r: r.get("text"))] == ["Paracetamol", "Aspirin"]


def test_render_dedups_and_formats() -> None:
    # The exact failure from the field: duplicate meds/results, unformatted vitals dates.
    summary = {
        "patient": {"phn": "42901168225", "name": "Baby Perera", "gender": "female", "birthDate": "2026-07-20"},
        "problems": [],
        "medications": [
            {"text": "Paracetamol", "ref": "MedicationRequest/1"},
            {"text": "Paracetamol", "ref": "MedicationRequest/2"},  # duplicate display
        ],
        "allergies": [],
        "vitals": [
            {"text": "Body weight", "value": 6.0, "unit": "kg", "when": "2026-07-27T00:00:00+00:00"},
            {"text": "Body weight", "value": 2.0, "unit": "kg", "when": "2026-07-20T00:00:00+00:00"},  # older
        ],
        "results": [
            {"text": "cxr chest", "critical": False, "ref": "DiagnosticReport/1"},
            {"text": "cxr chest", "critical": False, "ref": "DiagnosticReport/2"},  # duplicate
        ],
        "appointments": [{"start": "2026-07-27T11:41:23.738939+00:00", "status": "booked"}],
    }
    out = _render(summary, None)
    assert out.count("Paracetamol") == 1                 # meds deduped
    assert out.count("cxr chest") == 1                   # results deduped
    assert "Body weight 6 kg (27 Jul 2026)" in out       # latest-per-type, spaced, dated, no trailing .0
    assert "2.0" not in out and "6.0kg" not in out       # older reading dropped; unit spaced
    assert "27 Jul 2026, 11:41 (booked)" in out          # appointment formatted, no microseconds
    assert ".738939" not in out


async def test_context_skipped_without_bearer() -> None:
    # No token → no consent-checked read is possible → skip grounding (no network).
    assert await build_patient_context("http://core-api:8000", None, "55246820131") == ""
    assert await build_patient_context("http://core-api:8000", "Bearer x", "") == ""

"""Tests for the grounded-context builder (P1.1)."""

from __future__ import annotations

from app.agent.context import _render, build_patient_context

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


async def test_context_skipped_without_bearer() -> None:
    # No token → no consent-checked read is possible → skip grounding (no network).
    assert await build_patient_context("http://core-api:8000", None, "55246820131") == ""
    assert await build_patient_context("http://core-api:8000", "Bearer x", "") == ""

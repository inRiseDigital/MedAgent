"""Deterministic Rx-safety engine regression tests (04 §7, backlog 3.1).

The engine is the single source of prescribing verdicts — the LLM only narrates
it. These lock in the block/warn/pass decisions against dataset or logic drift.
Verdicts were confirmed against the live engine + curated dev datasets.
"""

from __future__ import annotations

from app.rxsafety.engine import screen


def test_clean_prescription_passes() -> None:
    assert screen(proposed_drug="amoxicillin", current_meds=[], allergies=[]).verdict == "pass"


def test_documented_allergy_ingredient_match_blocks() -> None:
    v = screen(proposed_drug="amoxicillin", current_meds=[],
               allergies=[{"substance": "amoxicillin", "criticality": "high"}])
    assert v.verdict == "block"
    assert any(f["code"] == "ALLERGY_MATCH" for f in v.findings)


def test_penicillin_to_cephalosporin_cross_reactivity_warns() -> None:
    v = screen(proposed_drug="cephalexin", current_meds=[],
               allergies=[{"substance": "penicillin", "criticality": "high"}])
    assert v.verdict == "warn"
    assert any(f["code"] == "ALLERGY_CROSS" for f in v.findings)


def test_major_ddi_blocks() -> None:
    # warfarin + an NSAID (ibuprofen) is a major bleeding-risk interaction -> block.
    v = screen(proposed_drug="ibuprofen", current_meds=["warfarin"], allergies=[])
    assert v.verdict == "block"


def test_dose_over_max_warns() -> None:
    v = screen(proposed_drug="paracetamol", current_meds=[], allergies=[], dose_mg_per_day=6000)
    assert v.verdict == "warn"
    assert any(f["code"] == "DOSE_EXCEEDED" for f in v.findings)


def test_unknown_drug_warns_not_passes() -> None:
    # An unrecognised drug must never silently pass.
    v = screen(proposed_drug="zzzdrug", current_meds=[], allergies=[])
    assert v.verdict == "warn"


def test_verdict_is_never_silently_downgraded() -> None:
    # Block must dominate warn/pass when multiple findings apply.
    v = screen(proposed_drug="amoxicillin", current_meds=["warfarin"],
               allergies=[{"substance": "amoxicillin", "criticality": "high"}])
    assert v.verdict == "block"

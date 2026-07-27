"""Deterministic-core regression tests for Track 4/6 clinical logic.

These guard the curated rulesets that decide clinical flags — imaging triage,
notifiable-disease classification, WHO growth deviation — none of which may
regress silently. All pure functions; no FHIR/DB.
"""

from __future__ import annotations

from app.routers.analytics import outbreak_signal
from app.routers.imaging import _classify as imaging_classify
from app.routers.patients import _assess_growth, _interp
from app.routers.referrals import can_transition
from app.routers.registry import classify_notifiable
from app.routers.schedule import order_waitlist


# --- Imaging triage (6.1) ---
def test_imaging_normal() -> None:
    flag, matched, review = imaging_classify(["Lungs clear, no acute abnormality"], "Normal", 0.97)
    assert flag == "normal" and matched == [] and review is False


def test_imaging_urgent_pneumothorax() -> None:
    flag, matched, review = imaging_classify(["Large left pneumothorax"], "Tension pneumothorax", 0.94)
    assert flag == "urgent" and "pneumothorax" in matched and review is False


def test_imaging_abnormal_low_confidence_forces_review() -> None:
    flag, matched, review = imaging_classify(["Possible small nodule"], "Indeterminate", 0.31)
    assert flag == "abnormal" and "nodule" in matched and review is True  # 0.31 < 0.50 floor


# --- Notifiable-disease classification (6.2) ---
def test_notifiable_by_icd() -> None:
    hit = classify_notifiable("A90", "Dengue fever")
    assert hit is not None and hit[0] == "dengue" and hit[2] is True  # immediately notifiable


def test_notifiable_by_text_fallback() -> None:
    hit = classify_notifiable(None, "Pulmonary tuberculosis confirmed")
    assert hit is not None and hit[0] == "tb" and hit[2] is False  # notifiable, not immediate


def test_non_notifiable() -> None:
    assert classify_notifiable("I10", "Essential hypertension") is None


def test_notifiable_icd_prefix_match() -> None:
    # B51 is a malaria sub-code; prefix match should still classify.
    hit = classify_notifiable("B51.0", "Plasmodium vivax")
    assert hit is not None and hit[0] == "malaria"


# --- WHO growth assessment (4.3) ---
def test_growth_underweight_and_stunted_at_birth() -> None:
    flags = _assess_growth("female", 0.0, 2.0, 44.0)  # below -2SD (2.4 kg / 45.4 cm)
    assert "underweight" in flags and "stunted" in flags


def test_growth_healthy_no_flags() -> None:
    flags = _assess_growth("female", 3.0, 6.0, 61.0)  # above -2SD at 3 months
    assert flags == []


def test_growth_interpolation_midpoint() -> None:
    # linear interp between 0mo (2.4) and 6mo (5.7) at 3mo = 4.05
    assert abs(_interp({0: 2.4, 6: 5.7}, 3.0) - 4.05) < 1e-6


def test_growth_unknown_age_no_flags() -> None:
    assert _assess_growth("male", None, 2.0, 40.0) == []


# --- Referral transitions (5.1) ---
def test_referral_legal_transitions() -> None:
    assert can_transition("requested", "accept") is True
    assert can_transition("accepted", "complete") is True
    assert can_transition("requested", "reject") is True


def test_referral_illegal_transitions() -> None:
    assert can_transition("completed", "accept") is False   # terminal
    assert can_transition("requested", "complete") is False  # must accept first
    assert can_transition("requested", "bogus") is False     # unknown action


# --- Waitlist auto-book ordering (5.2) ---
def test_waitlist_urgency_beats_arrival_order() -> None:
    waits = [
        {"id": "a", "priority": 3, "created": "2026-08-01T08:00:00Z"},  # routine, earliest
        {"id": "b", "priority": 2, "created": "2026-08-01T09:00:00Z"},  # urgent, later
        {"id": "c", "priority": 3, "created": "2026-08-01T08:30:00Z"},  # routine, middle
    ]
    order = [w["id"] for w in order_waitlist(waits)]
    assert order == ["b", "a", "c"]  # urgent first, then routine FIFO


# --- Outbreak early-warning thresholds (6.3) ---
def test_outbreak_signal_escalation() -> None:
    assert outbreak_signal("dengue", 2) == "none"    # below watch (3)
    assert outbreak_signal("dengue", 4) == "watch"   # >= watch, < alert (8)
    assert outbreak_signal("dengue", 8) == "alert"   # >= alert
    assert outbreak_signal("cholera", 1) == "alert"  # single-case disease trips immediately

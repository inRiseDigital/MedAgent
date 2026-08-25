"""Tests for the deterministic imaging triage classifier (FR-10, P6).

Locks down _classify: critical findings flag `urgent` (and outrank abnormal),
abnormal findings flag `abnormal`, an unremarkable study is `normal`, and a
low-confidence AI read forces radiologist review regardless of flag.
"""

from __future__ import annotations

from app.routers.imaging import _CONFIDENCE_FLOOR, _classify


def test_critical_finding_is_urgent() -> None:
    flag, matched, needs_review = _classify(["large pneumothorax on the left"], "", 0.9)
    assert flag == "urgent"
    assert "pneumothorax" in matched
    assert needs_review is False  # confidence above the floor


def test_critical_outranks_abnormal() -> None:
    # both an abnormal ("nodule") and a critical ("haemorrhage") term present
    flag, matched, _ = _classify(["nodule noted"], "acute haemorrhage", 0.8)
    assert flag == "urgent"
    assert "haemorrhage" in matched


def test_abnormal_finding() -> None:
    flag, matched, _ = _classify(["small nodule"], "", 0.8)
    assert flag == "abnormal"
    assert "nodule" in matched


def test_unremarkable_is_normal() -> None:
    flag, matched, _ = _classify(["clear lung fields"], "no acute process", 0.9)
    assert flag == "normal"
    assert matched == []


def test_low_confidence_forces_review() -> None:
    _, _, needs_review = _classify(["clear"], "", _CONFIDENCE_FLOOR - 0.01)
    assert needs_review is True
    # even an urgent, high-signal finding still reviews when confidence is low
    _, _, nr2 = _classify(["pneumothorax"], "", 0.1)
    assert nr2 is True

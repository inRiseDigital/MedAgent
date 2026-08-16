"""Structural safety tests (P2a): a `block` can never become a signable proposal,
and tools are persona-scoped."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import app.agent.tools as tools_mod
from app.agent.tools import FhirClient, build_patient_tools


def _tool(tools, name):  # noqa: ANN001
    return next(t for t in tools if t.name == name)


async def _empty_search(self, *_a: Any, **_k: Any):  # noqa: ANN001
    return []


def test_persona_scope_patient() -> None:
    names = {t.name for t in build_patient_tools("http://f", "pid", [], [], [], audience="patient")}
    assert "present_card" in names
    assert not ({"draft_prescription", "screen_medication"} & names), "patient leaked rx tools"


def test_persona_scope_clinician() -> None:
    names = {t.name for t in build_patient_tools("http://f", "pid", [], [], [], audience="clinician")}
    assert {"screen_medication", "draft_prescription"} <= names
    assert "present_card" not in names


async def test_block_verdict_is_never_staged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(FhirClient, "search", _empty_search)
    monkeypatch.setattr(
        tools_mod, "rx_screen",
        lambda *a, **k: SimpleNamespace(verdict="block", codes=["RXA-ALLERGY"], findings=[], dataset_version="t"),
    )
    sink: list[dict] = []
    tools = build_patient_tools("http://f", "pid", [], sink, [], audience="clinician")
    out = await _tool(tools, "draft_prescription").ainvoke({"drug": "amoxicillin", "dose_text": "500mg"})
    assert sink == [], "a BLOCK verdict must not stage a signable proposal"
    assert "BLOCK" in out.upper()


async def test_pass_verdict_is_staged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(FhirClient, "search", _empty_search)
    monkeypatch.setattr(
        tools_mod, "rx_screen",
        lambda *a, **k: SimpleNamespace(verdict="pass", codes=[], findings=[], dataset_version="t"),
    )
    sink: list[dict] = []
    tools = build_patient_tools("http://f", "pid", [], sink, [], audience="clinician")
    await _tool(tools, "draft_prescription").ainvoke({"drug": "azithromycin", "dose_text": "500mg OD"})
    assert len(sink) == 1 and sink[0]["verdict"] == "pass"

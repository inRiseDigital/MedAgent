"""Orchestrator graph skeleton tests (04 §2)."""

from __future__ import annotations

import pytest

from app.graph import build_graph
from app.graph.nodes import rx_safety_gate
from app.graph.state import AgentState, SafetyVerdict, assert_context_stamp


def _stamped_state(**overrides: object) -> AgentState:
    state: AgentState = {
        "clinician_id": "practitioner-1",
        "patient_id": "patient-1",
        "encounter_id": "encounter-1",
        "consent_scope": ["clinical.read"],
        "messages": [{"role": "user", "content": "summarise this patient"}],
    }
    state.update(overrides)  # type: ignore[typeddict-item]
    return state


def test_graph_compiles() -> None:
    graph = build_graph()
    assert graph is not None


def test_question_route_produces_stub_draft() -> None:
    graph = build_graph()
    result = graph.invoke(_stamped_state())
    assert result["intent"] == "question"
    assert result["draft"]  # summary stub answered
    assert "S1 stub" in result["draft"]


def test_rx_safety_gate_returns_schema_conformant_pass_verdict() -> None:
    update = rx_safety_gate(_stamped_state())
    verdict = update["safety"]
    assert isinstance(verdict, SafetyVerdict)
    assert verdict.verdict == "pass"
    assert verdict.codes == []
    assert verdict.rationale


def test_missing_context_stamp_fails_closed() -> None:
    incomplete: AgentState = {"messages": [{"role": "user", "content": "hi"}]}
    with pytest.raises(ValueError, match="context stamp"):
        assert_context_stamp(incomplete)
    graph = build_graph()
    with pytest.raises(ValueError, match="context stamp"):
        graph.invoke(incomplete)

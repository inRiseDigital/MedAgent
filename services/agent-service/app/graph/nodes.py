"""Orchestrator graph nodes — S1 stubs with real signatures (04 §2, §3).

Every node re-asserts the context stamp before doing work. Real logic lands:
summary agent + citations in S3, proposals + Rx-safety + interrupt in S4.
"""

from __future__ import annotations

import logging
from typing import Any

from app.graph.state import AgentState, SafetyVerdict, assert_context_stamp

logger = logging.getLogger(__name__)


def ingress(state: AgentState) -> dict[str, Any]:
    """Authz + consent + scope stamp (04 §2.1 ingress node).

    S1: validates that the caller populated the stamp. TODO(S3): re-check the
    care relationship via core-api's decision endpoint (02 §7.2).
    """
    assert_context_stamp(state)
    return {}


def classify_intent(state: AgentState) -> dict[str, Any]:
    """Intent classifier stub — routes question | write | schedule.

    S1: everything is a `question`. TODO(S3): LLM/structured classification.
    """
    assert_context_stamp(state)
    return {"intent": "question"}


def summary_agent(state: AgentState) -> dict[str, Any]:
    """Summary agent stub (agents/02).

    TODO(S3): FHIR read tools (citation-emitting), prompts/summary.v0.md as the
    system prompt seed, citation validator downstream. S1 returns a fixed
    stub answer so the streaming path is exercisable end-to-end.
    """
    assert_context_stamp(state)
    return {
        "draft": (
            "[S1 stub] The summary agent is not wired to the record yet. "
            "Real cited answers land in Sprint S3."
        )
    }


def rx_safety_gate(state: AgentState) -> dict[str, Any]:
    """Rx-safety gate stub (agents/03) — MANDATORY on the write path.

    The graph topology guarantees every MedicationRequest proposal passes
    through this node (safety is topology, not prompt instructions). S1
    returns a placeholder `pass` verdict with the real schema; the
    deterministic DDI/allergy engine lands in S4. NOTE: once real, absence of
    the DDI dataset must BLOCK proposals entirely (fail closed, 04 §7).
    """
    assert_context_stamp(state)
    verdict = SafetyVerdict(
        verdict="pass",
        codes=[],
        rationale="S1 placeholder verdict — deterministic DDI/allergy engine lands in S4.",
    )
    return {"safety": verdict}


def human_interrupt(state: AgentState) -> dict[str, Any]:
    """Clinician sign-off gate placeholder (FR-4.8).

    TODO(S4): LangGraph `interrupt()` persists graph state here; the UI renders
    the proposal card with the safety verdict; POST /agent/resume carries the
    signed / edited / rejected resolution (fresh step-up token required for
    prescriptions, 02 §5.2). Only a `signed` resolution reaches the commit node.
    """
    assert_context_stamp(state)
    logger.info("human-interrupt placeholder reached (sign-off flow lands S4)")
    return {"interrupt_pending": True}

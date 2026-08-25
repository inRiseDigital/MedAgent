"""Orchestrator graph nodes — S1 stubs with real signatures (04 §2, §3).

Every node re-asserts the context stamp before doing work. Real logic lands:
summary agent + citations in S3, proposals + Rx-safety + interrupt in S4.
"""

from __future__ import annotations

import logging
from typing import Any

from app.graph.state import AgentState, SafetyVerdict, assert_context_stamp
from app.rxsafety import screen as rx_screen

logger = logging.getLogger(__name__)

# Intent keywords — a fast deterministic classifier; an LLM refinement can layer
# on later, but the safety-relevant routing must never depend on a model.
_WRITE_KW = ("prescribe", "start ", "give ", "order ", "draft", "rx ", "put her on", "put him on")
_SCHED_KW = ("book", "appointment", "schedule", "refer ", "referral", "follow-up")


def ingress(state: AgentState) -> dict[str, Any]:
    """Authz + consent + scope stamp (04 §2.1 ingress node).

    S1: validates that the caller populated the stamp. TODO(S3): re-check the
    care relationship via core-api's decision endpoint (02 §7.2).
    """
    assert_context_stamp(state)
    return {}


def classify_intent(state: AgentState) -> dict[str, Any]:
    """Deterministic intent classifier — routes question | write | schedule.

    Keyword-based so routing (and therefore which safety path a turn takes) never
    depends on a model. `write` (prescribe/order a medication) is routed through
    the mandatory Rx-safety gate; everything else is a read `question`.
    """
    assert_context_stamp(state)
    msgs = state.get("messages", [])
    last = (msgs[-1]["content"] if msgs else "").lower()
    if any(k in last for k in _WRITE_KW):
        intent = "write"
    elif any(k in last for k in _SCHED_KW):
        intent = "schedule"
    else:
        intent = "question"
    return {"intent": intent}


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
    """Rx-safety gate (agents/03) — MANDATORY on the write path, FAIL-CLOSED.

    The graph topology guarantees every MedicationRequest proposal passes through
    this node (safety is topology, not prompt instructions), and a `block` verdict
    is routed straight to END — it can never reach the sign-off interrupt. The
    verdict is computed by the deterministic DDI/allergy engine; if there is no
    drug to screen or the engine raises, we BLOCK (absence of a clean verdict is
    never a pass — 04 §7).
    """
    assert_context_stamp(state)
    proposal = state.get("proposal") or {}
    drug = proposal.get("drug")
    if not drug:
        return {"safety": SafetyVerdict(
            verdict="block", codes=["NO_DRUG"],
            rationale="No drug on the proposal to screen — blocked (fail closed).")}
    active_meds = [str(m) for m in proposal.get("active_meds", [])]
    allergies = proposal.get("allergies", [])
    try:
        v = rx_screen(drug, active_meds, allergies)
    except Exception as exc:  # noqa: BLE001 — engine failure must fail closed
        logger.exception("rx-safety engine failed; blocking proposal")
        return {"safety": SafetyVerdict(
            verdict="block", codes=["ENGINE_UNAVAILABLE"],
            rationale=f"Rx-safety engine unavailable — blocked (fail closed): {exc}")}
    rationale = "; ".join(f.get("rationale", "") for f in v.findings) or \
        "No interaction, allergy or dose issue detected by the deterministic engine."
    return {"safety": SafetyVerdict(verdict=v.verdict, codes=list(v.codes), rationale=rationale)}


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

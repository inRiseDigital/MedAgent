"""Graph-topology safety tests (Stage B).

Proves the safety-relevant invariant is a property of the graph TOPOLOGY, not of
any prompt: a write turn must cross the deterministic Rx-safety gate, and a
`block` verdict is routed to END — it can never reach the sign-off interrupt.
"""

from __future__ import annotations

from app.graph.nodes import classify_intent
from app.graph.orchestrator import build_graph

STAMP = {"clinician_id": "dr1", "patient_id": "p1", "consent_scope": ["treat"]}


def _run(content: str, proposal: dict | None = None) -> dict:
    state: dict = {**STAMP, "messages": [{"role": "user", "content": content}]}
    if proposal is not None:
        state["proposal"] = proposal
    return build_graph().invoke(state)


def test_no_drug_fails_closed_and_never_signs() -> None:
    r = _run("please prescribe something", proposal={})
    assert r["safety"].verdict == "block"
    assert not r.get("interrupt_pending"), "a fail-closed BLOCK reached sign-off"


def test_allergy_conflict_blocks_and_never_signs() -> None:
    r = _run(
        "prescribe amoxicillin",
        proposal={"drug": "amoxicillin", "active_meds": [],
                  "allergies": [{"substance": "penicillin", "criticality": "high"}]},
    )
    assert r["safety"].verdict == "block", f"expected block, got {r['safety'].verdict}"
    assert not r.get("interrupt_pending"), "a BLOCK verdict reached the sign-off interrupt"


def test_clean_proposal_passes_and_reaches_signoff() -> None:
    r = _run("prescribe paracetamol", proposal={"drug": "paracetamol", "active_meds": [], "allergies": []})
    assert r["safety"].verdict in ("pass", "warn")
    assert r.get("interrupt_pending") is True


def test_question_skips_the_gate() -> None:
    r = _run("what are my recent lab results")
    assert r.get("intent") == "question"
    assert r.get("safety") is None and not r.get("interrupt_pending")


def test_intent_classification() -> None:
    def _intent(c: str) -> str:
        return classify_intent({**STAMP, "messages": [{"role": "user", "content": c}]})["intent"]

    assert _intent("please prescribe metformin") == "write"
    assert _intent("book me an appointment next week") == "schedule"
    assert _intent("summarise my allergies") == "question"

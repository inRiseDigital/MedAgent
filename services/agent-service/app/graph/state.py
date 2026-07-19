"""Typed graph state (04 §2.2).

The ingress node stamps every run with the verified request context
(clinician, patient, encounter, consent scope); every node and tool call
re-asserts the stamp so cross-patient access is impossible by construction —
the prototype's per-patient tool-scoping pattern, hardened.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field

Intent = Literal["question", "write", "schedule", "unknown"]


class SafetyVerdict(BaseModel):
    """Rx-safety gate output schema (agents/03).

    The verdict is computed by deterministic code (DDI dataset + allergy class
    rules — lands S4); an LLM only ever narrates it. `block` verdicts prevent
    the proposal from reaching the sign-off interrupt.
    """

    verdict: Literal["pass", "warn", "block"]
    codes: list[str] = Field(default_factory=list, description="rule/interaction codes that fired")
    rationale: str


class ChatMessage(TypedDict):
    role: Literal["user", "assistant", "system"]
    content: str


class AgentState(TypedDict, total=False):
    """State carried through one conversation turn (checkpointed per session)."""

    # --- context stamp (set once by ingress from the verified token; read-only after) ---
    clinician_id: str
    patient_id: str
    encounter_id: str | None
    consent_scope: list[str]

    # --- conversation ---
    messages: list[ChatMessage]

    # --- routing ---
    intent: Intent

    # --- work products ---
    draft: str | None
    proposal: dict[str, Any] | None  # typed Pydantic proposal models land S4
    safety: SafetyVerdict | None
    interrupt_pending: bool


def assert_context_stamp(state: AgentState) -> None:
    """Fail closed if a node runs without a complete context stamp (04 §2.2)."""
    missing = [k for k in ("clinician_id", "patient_id", "consent_scope") if not state.get(k)]
    if missing:
        raise ValueError(f"graph state missing context stamp fields: {missing}")

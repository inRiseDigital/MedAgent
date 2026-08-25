"""Orchestrator StateGraph definition (04 §2.1) — S1 topology skeleton.

Topology (the safety-relevant property is that the write path has NO edge that
bypasses the Rx-safety gate — safety is topology, not prompt instructions):

    START → ingress → intent
    intent —question→ summary → END          (citation validator inserted S3)
    intent —write→    rx_safety → interrupt → END   (proposal builder + commit S4)
    intent —schedule→ END                     (schedule agent lands S4/S5)

TODO(S3): Postgres checkpointer (langgraph-checkpoint-postgres over app_db;
tables created via Alembic in core-api's tree per 10 §9 rule 4), per-session
thread IDs, astream_events → AI SDK adapter.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from app.graph.nodes import (
    classify_intent,
    human_interrupt,
    ingress,
    rx_safety_gate,
    summary_agent,
)
from app.graph.state import AgentState


def _route_intent(state: AgentState) -> str:
    intent = state.get("intent", "unknown")
    if intent == "write":
        # The ONLY path for write intents runs through the Rx-safety gate.
        return "rx_safety"
    if intent == "question":
        return "summary"
    # schedule / unknown: nothing wired in S1.
    return END


def _route_safety(state: AgentState) -> str:
    """A `block` verdict NEVER reaches the sign-off interrupt — it is a hard stop
    routed straight to END. Only pass/warn proposals can be presented for signing.
    This makes "a blocked drug cannot be signed" a property of the topology."""
    safety = state.get("safety")
    if safety is not None and safety.verdict == "block":
        return END
    return "interrupt"


def build_graph() -> Any:
    """Compile the S1 orchestrator graph."""
    graph: StateGraph[AgentState] = StateGraph(AgentState)

    graph.add_node("ingress", ingress)
    graph.add_node("intent", classify_intent)
    graph.add_node("summary", summary_agent)
    graph.add_node("rx_safety", rx_safety_gate)
    graph.add_node("interrupt", human_interrupt)

    graph.add_edge(START, "ingress")
    graph.add_edge("ingress", "intent")
    graph.add_conditional_edges(
        "intent",
        _route_intent,
        {"summary": "summary", "rx_safety": "rx_safety", END: END},
    )
    graph.add_edge("summary", END)
    # No conditional bypass: every write proposal crosses the safety gate first,
    # and a `block` verdict is routed to END — only pass/warn reach the sign-off
    # interrupt. Safety is topology, not prompt instructions.
    graph.add_conditional_edges(
        "rx_safety",
        _route_safety,
        {"interrupt": "interrupt", END: END},
    )
    graph.add_edge("interrupt", END)

    return graph.compile()

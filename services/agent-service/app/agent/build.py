"""Clinical conversational agent (04 §2). A LangGraph ReAct agent over the
patient's FHIR record, scoped to one patient, that cites the resources it reads.

Phase A is a single summary/Q&A agent; the orchestrator + specialist roster
(rx-safety, lab, ...) in 04 §2.1 grow on this same tool/citation contract.
"""

from __future__ import annotations

from typing import Any

import httpx
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import create_react_agent

from app.agent.tools import PHN_SYSTEM, build_patient_tools
from app.config import Settings

SYSTEM_PROMPT = """You are a clinical AI assistant helping a doctor review ONE specific patient's medical record in real time. You read the record through FHIR tools.

Tools (call the relevant one(s) before answering — never rely on prior knowledge about this patient):
- get_patient_summary  → name, date of birth, gender, PHN
- get_conditions       → diagnoses / conditions (ICD-10)
- get_medications      → current and past prescriptions
- get_allergies        → allergies and intolerances with criticality
- get_vitals           → recent vital-sign observations

Rules:
- ALWAYS ground answers in tool output. Every clinical statement must carry the
  citation the tool returned, in the form [source: ResourceType/id]. Do not
  invent citations.
- If the record does not contain the answer, say so plainly and mark any general
  medical knowledge you add as [general knowledge] — never present it as this
  patient's data.
- Be concise and clinically precise. Proactively flag critical findings: severe
  allergies, potential drug interactions, abnormal vitals, chronic conditions.
- You SUPPORT the doctor's judgement; you do not make final clinical decisions,
  and you never state that you have prescribed, ordered, or committed anything —
  writes happen only through the doctor's explicit sign-off elsewhere.
- If asked something outside this patient's record or your tools, say so.
"""


async def resolve_patient_fhir_id(fhir_base_url: str, patient_ref: str) -> str | None:
    """Resolve a request patient id to a FHIR Patient logical id.

    Accepts either a FHIR Patient id directly, or a PHN (all-digit) which is
    looked up via the identifier search. Returns None if not found.
    """
    base = fhir_base_url.rstrip("/")
    async with httpx.AsyncClient(timeout=10.0) as client:
        if patient_ref.isdigit():
            resp = await client.get(
                f"{base}/Patient",
                params={"identifier": f"{PHN_SYSTEM}|{patient_ref}"},
                headers={"Accept": "application/fhir+json"},
            )
            resp.raise_for_status()
            entries = resp.json().get("entry", [])
            if entries:
                return str(entries[0]["resource"]["id"])
            # fall through: maybe it really is a numeric FHIR id
        resp = await client.get(
            f"{base}/Patient/{patient_ref}", headers={"Accept": "application/fhir+json"}
        )
        if resp.status_code == 200:
            return str(resp.json()["id"])
    return None


def build_agent(
    settings: Settings, patient_fhir_id: str, sources: list[dict[str, Any]]
) -> CompiledStateGraph:
    """Compile a patient-scoped ReAct agent. `sources` accumulates citations."""
    # NOTE: newer models (e.g. claude-sonnet-5) reject `temperature` — it is
    # deprecated for them — so we do not pass it. Determinism for the
    # safety-critical paths comes from the deterministic Rx engine (04 ADR AG-2),
    # not model temperature.
    llm = ChatAnthropic(
        model=settings.anthropic_model,
        api_key=settings.anthropic_api_key,
        max_tokens=2048,
        # Extended thinking is disabled: with tool-calling round-trips the
        # thinking blocks must be echoed back intact, which the LangChain
        # adapter mishandles ("thinking.thinking: Field required"). The clinical
        # agent does not need model-side reasoning traces.
        thinking={"type": "disabled"},
    )
    tools = build_patient_tools(settings.fhir_base_url, patient_fhir_id, sources)
    return create_react_agent(llm, tools, prompt=SystemMessage(content=SYSTEM_PROMPT))

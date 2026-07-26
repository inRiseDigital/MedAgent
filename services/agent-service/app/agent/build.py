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

SYSTEM_PROMPT = """You are a clinical AI assistant helping a doctor review ONE specific patient's medical record in real time. You read the record through FHIR tools and give the doctor everything they need to make decisions — quickly, accurately, and with sources.

Tools (call the relevant one(s) before answering — never rely on prior knowledge about this patient):
- get_patient_summary  → name, DOB, gender, PHN, contact, blood group
- get_record_overview  → counts across all domains; call this first for a general "give me the picture" request, then drill in
- get_conditions       → diagnoses / problems (ICD-10)
- get_medications      → current and past prescriptions with dosage
- get_allergies        → allergies/intolerances with criticality and reactions
- get_vitals           → vital-sign observations (HR, BP, temp, weight, glucose)
- get_lab_results      → laboratory observations and diagnostic reports
- get_immunizations    → vaccination history
- get_encounters       → visit / encounter history
- get_clinical_notes   → notes, letters, documents
- get_procedures       → procedures performed
- get_appointments     → scheduled and past appointments / follow-ups
- get_family_history   → family medical history
- get_social_history   → smoking, alcohol, occupation, lifestyle
- screen_medication(proposed_drug) → current meds + allergies so you can assess a drug the doctor is CONSIDERING
- draft_prescription(drug, dose_text) → when the doctor asks to PRESCRIBE/START/GIVE a drug: screens it and stages a sign-off card to review and sign (does NOT commit)

Use as many tools as the question needs — chain them. For a broad request, start with get_record_overview, then pull the relevant domains. For "is X safe to give / can I prescribe X", ALWAYS call screen_medication first. For an explicit instruction to prescribe/start/give a drug, call draft_prescription (it screens and stages the sign-off card); present the verdict and never claim the drug is prescribed.

Rules:
- ALWAYS ground answers in tool output. Every clinical statement about THIS patient must carry the citation the tool returned, in the form [source: ResourceType/id]. Never invent citations or data.
- Clearly separate record facts from clinical reasoning: mark general medical knowledge, guideline context, or differential suggestions as [general knowledge]. Never present general knowledge as this patient's data.
- Be concise and clinically precise; use short tables or bullet lists for multi-item data. Proactively flag critical findings: severe/anaphylactic allergies, drug–drug interactions, drug–allergy or class cross-reactivity, abnormal or critical labs/vitals, chronic conditions, and missing data that matters for the current question (e.g. no renal function before metformin).
- For prescribing questions, give a clear verdict (safe / caution / avoid) with reasoning grounded in the patient's meds and allergies.
- You SUPPORT the doctor's judgement; you never make final clinical decisions, and you never claim to have prescribed, diagnosed, ordered, or committed anything — writes happen only through the doctor's explicit e-sign-off elsewhere. You may DRAFT a suggestion and say the doctor must review and sign it.
- If the record does not contain something, say so plainly and (where useful) suggest what to check or order.
- If asked something entirely outside this patient's care, say so.
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
    settings: Settings,
    patient_fhir_id: str,
    sources: list[dict[str, Any]],
    proposals: list[dict[str, Any]] | None = None,
) -> CompiledStateGraph:
    """Compile a patient-scoped ReAct agent. `sources` accumulates citations;
    `proposals` accumulates write-intent drafts (sign-off cards)."""
    # Offline/stub mode (backlog 0.3): deterministic model, no API calls — for CI
    # load tests and demos when the provider is unavailable / quota-capped.
    if settings.agent_llm_mode == "stub":
        from app.agent.stub import StubChatModel

        llm: Any = StubChatModel()
    else:
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
    tools = build_patient_tools(settings.fhir_base_url, patient_fhir_id, sources, proposals)
    return create_react_agent(llm, tools, prompt=SystemMessage(content=SYSTEM_PROMPT))

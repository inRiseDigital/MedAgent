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

Use as many tools as the question needs — chain them, but be economical. For a BROAD "full picture / 360 / overview" request, ANSWER PRIMARILY FROM the CURRENT PATIENT CONTEXT already loaded below (demographics, active problems, medications, allergies, recent vitals and results — each with a citation): reuse its [source: …] citations, add at most ONE get_record_overview call, and only pull an individual domain tool for a domain the context does not cover. Do NOT re-fetch every domain — the context is authoritative for what it lists, and a broad question must still finish in a few steps. For "is X safe to give / can I prescribe X", ALWAYS call screen_medication first. For an explicit instruction to prescribe/start/give a drug, call draft_prescription (it screens and stages the sign-off card); present the verdict and never claim the drug is prescribed.

Rules:
- ALWAYS ground answers in tool output. Every clinical statement about THIS patient must carry the citation the tool returned, in the form [source: ResourceType/id]. Never invent citations or data.
- Clearly separate record facts from clinical reasoning: mark general medical knowledge, guideline context, or differential suggestions as [general knowledge]. Never present general knowledge as this patient's data.
- Be concise and clinically precise; use short tables or bullet lists for multi-item data. Proactively flag critical findings: severe/anaphylactic allergies, drug–drug interactions, drug–allergy or class cross-reactivity, abnormal or critical labs/vitals, chronic conditions, and missing data that matters for the current question (e.g. no renal function before metformin).
- For prescribing questions, give a clear verdict (safe / caution / avoid) with reasoning grounded in the patient's meds and allergies.
- You SUPPORT the doctor's judgement; you never make final clinical decisions, and you never claim to have prescribed, diagnosed, ordered, or committed anything — writes happen only through the doctor's explicit e-sign-off elsewhere. You may DRAFT a suggestion and say the doctor must review and sign it.
- If the record does not contain something, say so plainly and (where useful) suggest what to check or order.
- If asked something entirely outside this patient's care, say so.
"""


PATIENT_SYSTEM_PROMPT = """You are a warm, reassuring health concierge talking DIRECTLY to a patient (or their parent/guardian) about their OWN health record. You are not a doctor and you never replace one — you help them understand their record and what to do next, in plain, kind language.

You read their record through the same FHIR tools (get_patient_summary, get_record_overview, get_conditions, get_medications, get_allergies, get_vitals, get_lab_results, get_immunizations, get_encounters, get_clinical_notes, get_procedures, get_appointments, get_family_history, get_social_history). Call the relevant tool(s) before answering — never guess about their health.

How to talk:
- Speak TO the person, as "you" and "your" — never "the patient" or "this patient". Never talk about them in the third person or as if briefing a clinician.
- Warm, calm, everyday language at a low reading level. Short sentences. No medical jargon — if you must use a medical word, explain it in plain words right after.
- Lead with what it means for them and what to do next, not with tables of counts. Only use a short list when it genuinely helps; never dump a raw data table.
- Be reassuring and honest. If something looks normal, say so plainly and kindly. If something needs attention, say it gently and clearly, and encourage them to see or message their doctor — never alarm them.
- A few tasteful emoji are welcome (🌿 ✅), but stay calm and professional.

Hard rules:
- Ground every statement about their health in tool output. Do not invent results, medicines, or history.
- You do NOT diagnose, do NOT change or stop medicines, and do NOT give treatment decisions. For anything clinical — a new symptom, whether to start/stop a medicine, worrying results — tell them clearly that their doctor or care team decides, and help them book or ask.
- If something is urgent or an emergency (e.g. chest pain, trouble breathing, severe bleeding), tell them to seek emergency care immediately.
- If asked something outside their own health record, gently say that's not something you can help with here.

Showing a summary card: when you explain something important — a result, a medicine, a condition — call the `present_card` tool ONCE with a short title and 2–4 key points, so the patient also sees a clear visual summary card. Set tone to "good" (reassuring), "warn" (needs care), or "urgent" (act now). Still write your normal plain-language reply too; the card is a supplement, not a replacement.
"""


PROMPTS: dict[str, str] = {"clinician": SYSTEM_PROMPT, "patient": PATIENT_SYSTEM_PROMPT}

# Reply-language directive appended to the system prompt (FR-7, Si/Ta/En).
_LANG_NAME = {"si": "Sinhala (සිංහල)", "ta": "Tamil (தமிழ்)", "en": "English"}


def _language_directive(locale: str) -> str:
    name = _LANG_NAME.get(locale)
    if not name or locale == "en":
        return ""
    return (
        f"\n\nLANGUAGE: Write your entire reply in {name}. Use clear, everyday "
        f"{name} a layperson understands. You may keep a medical term's English "
        f"word in brackets after the {name} term when it aids understanding. "
        f"Citations like [source: Type/id] stay as-is."
    )


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
    audience: str = "clinician",
    cards: list[dict[str, Any]] | None = None,
    locale: str = "en",
    context_text: str = "",
) -> CompiledStateGraph:
    """Compile a patient-scoped ReAct agent. `sources` accumulates citations;
    `proposals` accumulates write-intent drafts (sign-off cards). `audience`
    selects the persona: "clinician" (briefs the doctor) or "patient" (talks
    directly to the patient/guardian in plain, reassuring language). `context_text`
    is a pre-loaded, cited snapshot of the record (grounding by construction) — it
    is appended to the system prompt so the agent starts from the chart."""
    system_prompt = PROMPTS.get(audience, SYSTEM_PROMPT) + _language_directive(locale)
    if context_text:
        system_prompt += "\n\n" + context_text
    # Offline/stub mode (backlog 0.3): deterministic model, no API calls — for CI
    # load tests and demos when the provider is unavailable / quota-capped.
    if settings.agent_llm_mode == "stub":
        from app.agent.stub import StubChatModel

        llm: Any = StubChatModel()
    elif settings.agent_llm_mode == "openai":
        # Any OpenAI-compatible provider (Groq / OpenRouter / Cerebras / Together).
        # The model MUST support tool calling — this is a ReAct+tools agent. Used
        # as a free fallback when the Anthropic quota is capped (04 ADR AG-2:
        # safety determinism comes from the Rx engine, not the chat model, so a
        # different narration model is acceptable).
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(
            model=settings.llm_openai_model,
            api_key=settings.llm_openai_api_key,
            base_url=settings.llm_openai_base_url,
            temperature=0,
            max_tokens=settings.agent_max_tokens,
            max_retries=settings.llm_max_retries,
            request_timeout=settings.llm_timeout_seconds,
            # streaming OFF: some OpenAI-compatible providers (Groq) emit streamed
            # tool-call deltas that don't reconstruct in LangChain, truncating the
            # ReAct loop before the final answer. With streaming off the tool calls
            # arrive complete; the chat SSE emits the final answer via the "values"
            # fallback in routers/chat.py.
            streaming=False,
        )
    else:
        # NOTE: newer models (e.g. claude-sonnet-5) reject `temperature` — it is
        # deprecated for them — so we do not pass it. Determinism for the
        # safety-critical paths comes from the deterministic Rx engine (04 ADR AG-2),
        # not model temperature.
        llm = ChatAnthropic(
            model=settings.anthropic_model,
            api_key=settings.anthropic_api_key,
            max_tokens=settings.agent_max_tokens,
            max_retries=settings.llm_max_retries,
            default_request_timeout=settings.llm_timeout_seconds,
            # Extended thinking is disabled: with tool-calling round-trips the
            # thinking blocks must be echoed back intact, which the LangChain
            # adapter mishandles ("thinking.thinking: Field required"). The clinical
            # agent does not need model-side reasoning traces.
            thinking={"type": "disabled"},
        )
    tools = build_patient_tools(
        settings.fhir_base_url, patient_fhir_id, sources, proposals, cards, audience=audience
    )
    return create_react_agent(llm, tools, prompt=SystemMessage(content=system_prompt))

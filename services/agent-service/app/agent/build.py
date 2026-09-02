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

from app.agent.tools import PHN_SYSTEM, build_patient_tools, fhir_headers
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

Use as many tools as the question needs — chain them, but be economical. For a BROAD "full picture / 360 / overview" request, ANSWER PRIMARILY FROM the CURRENT PATIENT CONTEXT already loaded below (demographics, active problems, medications, allergies, recent vitals and results — each with a citation): reuse its [source: …] citations, add at most ONE get_record_overview call, and only pull an individual domain tool for a domain the context does not cover. Do NOT re-fetch every domain — the context is authoritative for what it lists, and a broad question must still finish in a few steps. For "is X safe to give / can I prescribe X", ALWAYS call screen_medication first. For an explicit instruction to prescribe/start/give a drug, call draft_prescription (it screens and stages the sign-off card); present the verdict and never claim the drug is prescribed. When your answer contains structured or visual data — a value over time, key numbers, a list of record items, or suggested next actions — ALSO call render_widget to render it as a chat component (metric-trend, stat-grid, record-links, safety-alert, next-best-action), then write a short reply alongside it.

Rules:
- ALWAYS ground answers in tool output. Every clinical statement about THIS patient must carry the citation the tool returned, in the form [source: ResourceType/id]. Never invent citations or data.
- Clearly separate record facts from clinical reasoning: mark general medical knowledge, guideline context, or differential suggestions as [general knowledge]. Never present general knowledge as this patient's data. For up-to-date guidelines/drug information NOT in the record you MAY call web_search and label each result [web: url]; keep the patient's cited record facts ([source: …]) strictly separate from web/general knowledge.
- Be concise and clinically precise; use short tables or bullet lists for multi-item data. Proactively flag critical findings: severe/anaphylactic allergies, drug–drug interactions, drug–allergy or class cross-reactivity, abnormal or critical labs/vitals, chronic conditions, and missing data that matters for the current question (e.g. no renal function before metformin).
- For prescribing questions, give a clear verdict (safe / caution / avoid) with reasoning grounded in the patient's meds and allergies.
- You SUPPORT the doctor's judgement; you never make final clinical decisions, and you never claim to have prescribed, diagnosed, ordered, or committed anything — writes happen only through the doctor's explicit e-sign-off elsewhere. You may DRAFT a suggestion and say the doctor must review and sign it.
- If the record does not contain something, say so plainly and (where useful) suggest what to check or order.
- If asked something entirely outside this patient's care, say so.
- Adapt to the doctor over time: when they state a durable preference for HOW you should respond — brevity, depth of detail, format (tables vs prose), language — call `remember` with a short note so you match it next time. NEVER store clinical facts, patient data, or anything safety-relevant this way (those stay in the cited record and the deterministic safety engine); remember only response-style preferences.
"""


PATIENT_SYSTEM_PROMPT = """You are a warm, reassuring health concierge talking DIRECTLY to a patient (or their parent/guardian) about their OWN health record. You are not a doctor and you never replace one — you help them understand their record and what to do next, in plain, kind language.

You read their record through the same FHIR tools (get_patient_summary, get_record_overview, get_conditions, get_medications, get_allergies, get_vitals, get_lab_results, get_immunizations, get_encounters, get_clinical_notes, get_procedures, get_appointments, get_family_history, get_social_history). Call the relevant tool(s) before answering — never guess about their health. For general health questions not about their own record (e.g. "what is metformin", "is this vaccine safe"), you may use web_search and mention it's general info [web: source]; always keep it separate from their own record.

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

Showing a summary card: when you explain something important — a result, a medicine, a condition — call the `present_card` tool ONCE with a short title and 2–4 key points, so the patient also sees a clear visual summary card. Set tone to "good" (reassuring), "warn" (needs care), or "urgent" (act now). Still write your normal plain-language reply too; the card is a supplement, not a replacement. For structured or visual info (a value over time, a list of things in their record, suggested next steps) you may also call `render_widget` (metric-trend, record-links, next-best-action) to show it as a friendly chat component. Acting for them (always via a Confirm card — the patient taps to commit, you never commit): when they ask to REFILL or renew a medication, call `request_refill` with the exact medicine name; when they want to BOOK/see a doctor/schedule a visit or follow-up, call `book_appointment` with a short reason; when they want a VIDEO visit/call, call `start_video`. Each shows a Confirm card and does nothing until they tap it — never say something is already refilled, booked, or connected.

Learning them over time: when they tell you a lasting PREFERENCE, or you notice one — "explain things very simply", a language they use, a worry (e.g. anxious about needles), a topic they keep following up on — call `remember` with a short note so you help them better next time. Anything the record already stores in their memory is shown to you above; honour it. NEVER store clinical facts this way (those live in the record and stay cited); remember only preferences and how best to help.
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
                headers=fhir_headers(),
            )
            resp.raise_for_status()
            entries = resp.json().get("entry", [])
            if entries:
                return str(entries[0]["resource"]["id"])
            # fall through: maybe it really is a numeric FHIR id
        resp = await client.get(
            f"{base}/Patient/{patient_ref}", headers=fhir_headers()
        )
        if resp.status_code == 200:
            return str(resp.json()["id"])
    return None


def build_system_prompt(audience: str, locale: str, context_text: str = "") -> str:
    """Persona prompt + reply-language directive + (optional) the pre-loaded cited
    context. Shared by the ReAct agent and the direct-synthesis fast path."""
    prompt = PROMPTS.get(audience, SYSTEM_PROMPT) + _language_directive(locale)
    if context_text:
        prompt += "\n\n" + context_text
    return prompt


def build_chat_llm(settings: Settings, streaming: bool = False) -> Any:
    """Construct the configured chat model (stub / OpenAI-compatible / Anthropic).

    `streaming` is OFF for the ReAct loop: some OpenAI-compatible providers (Groq)
    emit streamed tool-call deltas that don't reconstruct in LangChain, truncating
    the loop before the final answer — with it off, tool calls arrive complete and
    chat.py emits the final answer via the "values" fallback. The tool-free direct
    synthesis path turns streaming ON so its answer streams token by token.
    """
    if settings.agent_llm_mode == "stub":
        from app.agent.stub import StubChatModel

        return StubChatModel()
    if settings.agent_llm_mode == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=settings.llm_openai_model,
            api_key=settings.llm_openai_api_key,
            base_url=settings.llm_openai_base_url,
            temperature=0,
            max_tokens=settings.agent_max_tokens,
            max_retries=settings.llm_max_retries,
            request_timeout=settings.llm_timeout_seconds,
            streaming=streaming,
            # Reasoning models (Qwen, gpt-oss) otherwise emit their chain-of-thought
            # inline as <think>…</think>; Groq's reasoning_format=hidden returns only
            # the final answer. Passed via extra_body (a raw request-body field) —
            # the OpenAI SDK rejects it as a top-level arg. Ignored by providers that
            # don't know it.
            extra_body={"reasoning_format": "hidden"},
        )
    # NOTE: newer Claude models reject `temperature`; determinism for the safety
    # paths comes from the deterministic Rx engine (04 ADR AG-2), not temperature.
    # ChatAnthropic streams via astream natively; no streaming flag needed.
    return ChatAnthropic(
        model=settings.anthropic_model,
        api_key=settings.anthropic_api_key,
        max_tokens=settings.agent_max_tokens,
        max_retries=settings.llm_max_retries,
        default_request_timeout=settings.llm_timeout_seconds,
        thinking={"type": "disabled"},
    )


def build_react_llm(settings: Settings) -> Any:
    """The model for the tool-using ReAct loop (specific Q&A that needs read tools).

    Prefer Anthropic Claude here EVEN WHEN the configured chat mode is Groq/OpenAI:
    an OpenAI-compatible reasoning model (Qwen) doesn't stream the post-tool answer
    through LangGraph and takes ~15-45s per round-trip, so a multi-tool ask blanks
    for up to the timeout. Claude streams the answer token by token (it appears
    immediately, no timeout floor) and needs fewer round-trips. The instant fast
    paths (overview synthesis, proactive greeting, deterministic actions) stay on
    the configured model — this only swaps the slow tool loop. Falls back to the
    configured model when Anthropic isn't available (no key / stub mode)."""
    if settings.agent_react_provider == "anthropic" and settings.anthropic_api_key:
        return ChatAnthropic(
            model=settings.anthropic_model,
            api_key=settings.anthropic_api_key,
            max_tokens=settings.agent_max_tokens,
            max_retries=settings.llm_max_retries,
            default_request_timeout=settings.llm_timeout_seconds,
            thinking={"type": "disabled"},
        )
    return build_chat_llm(settings)


def build_agent(
    settings: Settings,
    patient_fhir_id: str,
    sources: list[dict[str, Any]],
    proposals: list[dict[str, Any]] | None = None,
    audience: str = "clinician",
    cards: list[dict[str, Any]] | None = None,
    widgets: list[dict[str, Any]] | None = None,
    remember_fn: Any = None,
    locale: str = "en",
    context_text: str = "",
) -> CompiledStateGraph:
    """Compile a patient-scoped ReAct agent. `sources` accumulates citations;
    `proposals` accumulates write-intent drafts (sign-off cards). `audience`
    selects the persona: "clinician" (briefs the doctor) or "patient" (talks
    directly to the patient/guardian in plain, reassuring language). `context_text`
    is a pre-loaded, cited snapshot of the record (grounding by construction) — it
    is appended to the system prompt so the agent starts from the chart."""
    system_prompt = build_system_prompt(audience, locale, context_text)
    llm = build_react_llm(settings)  # tool loop → Claude (streams; see build_react_llm)
    tools = build_patient_tools(
        settings.fhir_base_url, patient_fhir_id, sources, proposals, cards, widgets,
        remember_fn=remember_fn, audience=audience,
    )
    return create_react_agent(llm, tools, prompt=SystemMessage(content=system_prompt))

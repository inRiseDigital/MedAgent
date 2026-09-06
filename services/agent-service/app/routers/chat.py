"""POST /api/v1/chat — streaming cited chat over the patient's FHIR record (04 §2).

Runs the patient-scoped LangGraph agent and adapts its token stream to the
**Vercel AI SDK data (UI message) protocol over SSE** — typed frames the web app
consumes with `useChat`. Citations gathered by the read tools are emitted as a
`data-citations` part so the UI can render source chips (FR-3.4).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agent.build import (
    build_agent,
    build_chat_llm,
    build_system_prompt,
    resolve_patient_fhir_id,
)
from app.agent.context import build_patient_context
from app.agent.memory import recall as recall_memory
from app.agent.memory import remember as remember_memory
from app.agent.memory import render_memory_block
from app.agent.telemetry import record_turn
from app.agent.threads import append_turn, load_thread
from app.auth import Principal, require_user
from app.config import Settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    messages: list[dict[str, Any]] = Field(min_length=1)
    patient_id: str
    encounter_id: str | None = None
    # Persona hint: "patient" → warm, plain-language concierge; anything else →
    # clinician briefing. Not a security boundary — data access is patient-scoped
    # by fhir_id regardless — only the tone/framing of the narration changes.
    audience: str = "clinician"
    # UI locale: the assistant replies in this language (en | si | ta).
    locale: str = "en"
    # Stable id for this conversation thread (memory scoping; future resume).
    conversation_id: str | None = None
    # "chat" (a user turn) or "proactive" (agent-initiated grounded greeting/nudge).
    mode: str = "chat"


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _latest_user_text(messages: list[dict[str, Any]]) -> str:
    """Newest user message text, tolerating a plain `content` string or the AI SDK `parts` array."""
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str) and content.strip():
            return content
        text = "".join(
            p.get("text", "")
            for p in msg.get("parts", [])
            if isinstance(p, dict) and p.get("type") == "text"
        )
        if text.strip():
            return text
    return ""


def _to_agent_messages(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Map the client's message array to the agent's input, PRESERVING history.

    The web client already sends the whole conversation; forwarding only the
    latest turn (the old behaviour) made the agent single-turn and stateless —
    it forgot everything said earlier. Keep user/assistant turns with real text;
    the system persona is supplied by the agent itself.
    """
    out: list[dict[str, str]] = []
    for msg in messages:
        role = msg.get("role")
        if role not in ("user", "assistant"):
            continue
        content = msg.get("content")
        if not isinstance(content, str) or not content.strip():
            content = "".join(
                p.get("text", "")
                for p in msg.get("parts", [])
                if isinstance(p, dict) and p.get("type") == "text"
            )
        if content.strip():
            out.append({"role": role, "content": content})
    return out


_OVERVIEW_KW = (
    "360", "full profile", "full picture", "complete profile", "complete picture",
    "overview", "whole record", "entire record", "full record", "full summary",
    "profile of this patient", "summarise this patient", "summarize this patient",
    "everything about", "give me the full", "complete overview", "full clinical picture",
)


def _is_broad_overview(question: str) -> bool:
    """A broad 'give me the whole picture' request — answered from the pre-loaded
    cited context in one streamed pass, not by crawling every read tool."""
    q = (question or "").lower()
    return any(k in q for k in _OVERVIEW_KW)


def _overview_from_context(record_context: str, audience: str = "patient") -> str:
    """A grounded 360 assembled DIRECTLY from the pre-loaded cited context — the
    resilient fallback when the model can't synthesise in time. The context is already
    a cited snapshot of the chart; here we PARSE its labelled lines and re-present them
    as a clean, sectioned profile (Who · Safety · Physical health · Care), grouped by
    dimension rather than dumped as-is. Guarantees a useful, well-structured, grounded
    360 even when the language model is slow or unavailable — never a raw data glitch.

    It is also honest: mental-health and social history are not separate structured
    fields in this record, so the absence of them here is not evidence of wellbeing —
    we say so plainly rather than implying the clinical data is the whole person."""
    # Parse "- Label: body." lines from the cited context into a label→body map,
    # stripping the inline [source: …] markers (citations stream separately as chips).
    sections: dict[str, str] = {}
    for ln in record_context.splitlines():
        s = ln.strip().lstrip("-").strip()
        if not s or s.startswith("CURRENT PATIENT CONTEXT"):
            continue
        s = re.sub(r"\s*\[source:[^\]]*\]", "", s)
        s = re.sub(r"\s+([;.,])", r"\1", s).strip().rstrip(".")
        label, sep, body = s.partition(":")
        if sep and body.strip():
            sections[label.strip()] = body.strip()
    if not sections:
        return ""

    who = sections.get("Patient", "")
    name = who.split(",")[0].strip() if who else "this patient"
    patient_facing = audience != "clinician"

    lines: list[str] = [f"Here's a 360° view of **{name}**, straight from the record:", ""]

    def add(header: str, rows: list[tuple[str, str | None]]) -> None:
        body = [f"- **{lbl}:** {val}" for lbl, val in rows if val]
        if body:
            lines.append(f"**{header}**")
            lines.extend(body)
            lines.append("")

    add("Who", [("Details", who)] if who else [])
    add("Safety", [
        ("Alerts", sections.get("SAFETY FLAGS (deterministic)")),
        ("Allergies", sections.get("Allergies")),
    ])
    add("Physical health", [
        ("Active problems", sections.get("Active problems")),
        ("Medications", sections.get("Active medications")),
        ("Recent vitals", sections.get("Recent vitals")),
        ("Recent results", sections.get("Recent results")),
    ])
    add("Upcoming care", [("Appointments", sections.get("Appointments"))])

    note = (
        "Not captured as separate structured fields in this record — the above is the "
        "clinical data on file, so this section being empty is not a sign that all is well. "
        + ("Tell me if you'd like to talk about how you're doing."
           if patient_facing else
           "Consider a psychosocial history if clinically relevant.")
    )
    lines.append("**Mental & social wellbeing**")
    lines.append(f"- {note}")
    return "\n".join(lines).strip()


# ---- patient ACTION intent (refill / book / video) --------------------------
# A clear action request is answered INSTANTLY with a Confirm card (the same
# widget the tools stage), skipping the slow tool loop. The model still only
# proposes — the card commits nothing until the patient taps it.
_REFILL_KW = ("refill", "re-fill", "renew")
_BOOK_KW = ("book a", "book an", "book me", "book my", "schedule a", "schedule an",
            "schedule me", "make an appointment", "set up an appointment",
            "arrange an appointment", "get an appointment")
_VIDEO_KW = ("video call", "video visit", "video consult", "video appointment",
             "start a video", "video with", "call by video", "see a doctor by video")
# If the ask carries clinical nuance, defer to the full agent (it may need to
# reason/answer, not just stage a card).
_ACTION_GUARD = ("should i", "should we", "can i stop", "do i still", "side effect",
                 "instead of", "or stop", "or should", "is it safe", "why am i", "what is",
                 "what's", "how does", "interact")


def _active_meds(record_context: str) -> list[str]:
    """Active medication display strings from the pre-loaded context (names + dose)."""
    for line in record_context.splitlines():
        if "Active medications:" in line:
            seg = line.split("Active medications:", 1)[1]
            meds = []
            for item in seg.split(";"):
                name = re.sub(r"\s*\[source:[^\]]*\]", "", item).strip().strip(".").strip()
                if name:
                    meds.append(name)
            return meds
    return []


def _detect_patient_action(question: str, record_context: str) -> dict[str, str] | None:
    """Detect a clear refill/book/video request → an action to stage as a Confirm
    card, or None to let the full agent handle it. Conservative: clinical-nuance
    phrasing defers to the agent, and an un-named refill among several meds defers."""
    q = (question or "").lower()
    if not q.strip() or any(g in q for g in _ACTION_GUARD):
        return None
    if any(k in q for k in _VIDEO_KW):
        return {"kind": "video"}
    if any(k in q for k in _REFILL_KW):
        meds = _active_meds(record_context)
        for m in meds:  # a named medicine wins
            drug = (m.split() or [""])[0].lower()
            if len(drug) >= 4 and drug in q:
                return {"kind": "refill", "med": m}
        if len(meds) == 1:  # only one active med → unambiguous
            return {"kind": "refill", "med": meds[0]}
        return None  # ambiguous — let the agent ask which one
    if any(k in q for k in _BOOK_KW):
        reason = "a follow-up" if ("follow" in q or "review" in q) else "a visit"
        return {"kind": "book", "reason": reason}
    return None


def _action_widget(action: dict[str, str]) -> tuple[dict[str, Any], str]:
    """Build the confirm-action widget + a short friendly reply for a patient action."""
    kind = action["kind"]
    if kind == "refill":
        med = action["med"]
        return (
            {"id": "w_act", "kind": "confirm-action", "title": "Refill request",
             "data": {"action": "refill", "params": {"medication": med},
                      "prompt": f"Request a refill for {med}?", "confirmLabel": "Confirm refill",
                      "doneLabel": f"Refill requested for {med}"}},
            f"Sure — I can request a refill for **{med}**. Tap **Confirm** below and I'll send it to "
            "your prescriber's team. 💊",
        )
    if kind == "book":
        reason = action.get("reason", "a visit")
        return (
            {"id": "w_act", "kind": "confirm-action", "title": "Book an appointment",
             "data": {"action": "book", "params": {"reason": reason},
                      "prompt": f"Find available times for {reason}?", "confirmLabel": "Show me times",
                      "doneLabel": "Finding available times…"}},
            f"Happy to help you book {reason}. Tap **Confirm** and I'll pull up the next available "
            "times to choose from. 📅",
        )
    return (
        {"id": "w_act", "kind": "confirm-action", "title": "Video visit",
         "data": {"action": "video", "params": {},
                  "prompt": "Start a secure video visit now?", "confirmLabel": "Start video visit",
                  "doneLabel": "Connecting to a secure room…"}},
        "I can connect you to a secure video visit — your clinician joins from their side. Tap "
        "**Confirm** when you're ready. 🎥",
    )


# ---- planner (S5): decompose a multi-part ask into a visible plan --------------
_PLAN_HINTS = (" and also ", " and then ", ", and ", " then ", "as well as",
               "along with", "after that")
_PLAN_VERBS = ("explain", "show", "book", "refill", "check", "tell me", "what",
               "when", "list", "summar", "review", "compare", "order", "find", "give me")


def _is_multipart(question: str) -> bool:
    """A request with several distinct parts — worth planning out loud. Conservative:
    a single-intent ask never triggers the planner (and its extra call)."""
    q = (question or "").lower()
    if q.count("?") >= 2:
        return True
    verb_hits = sum(1 for v in _PLAN_VERBS if v in q)
    if verb_hits >= 2 and (" and " in q or " then " in q):
        return True
    return len(q) > 45 and any(h in q for h in _PLAN_HINTS)


async def _make_plan(settings: Settings, question: str) -> list[str]:
    """A short ordered plan (2–5 steps) the agent will follow — one quick, bounded,
    best-effort model call. Returns [] on any miss (the agent just proceeds)."""
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        llm = build_chat_llm(settings, streaming=False)
        sys = (
            "You are planning how to answer a clinician/patient question about ONE patient's "
            "record. Break the request into 2 to 5 short, ordered steps you will take. Reply with "
            "ONLY a numbered list, one short step per line (max ~8 words each). No preamble, no prose."
        )
        async with asyncio.timeout(30):
            resp = await llm.ainvoke([SystemMessage(content=sys), HumanMessage(content=question)])
        steps: list[str] = []
        for line in _delta_text(resp).splitlines():
            m = re.match(r"^\s*(?:\d+[.)]|[-*•])\s*(.+)$", line.strip())
            if m:
                steps.append(m.group(1).strip()[:80])
        return steps[:5]
    except Exception:  # noqa: BLE001 — planning is best-effort; never blocks the answer
        logger.exception("plan generation failed")
        return []


async def _reflect(settings: Settings, plan: list[str], answer: str) -> str:
    """Self-critique (S5): given the plan and the answer produced, return a short
    note naming the ONE most important plan step the answer did NOT address, or ""
    if it's complete. Bounded, best-effort; runs only for planned multi-part asks so
    a genuine gap in a complex answer gets surfaced without re-answering."""
    if not plan or not answer.strip():
        return ""
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        llm = build_chat_llm(settings, streaming=False)
        sys = (
            "You are a terse reviewer checking whether an ANSWER covered its PLAN. If every plan "
            "step is addressed, reply with exactly COMPLETE. Otherwise reply with ONE short sentence "
            "naming the single most important step that was missed. No other text."
        )
        msg = "PLAN:\n" + "\n".join(f"- {s}" for s in plan) + f"\n\nANSWER:\n{answer[:2500]}"
        async with asyncio.timeout(25):
            resp = await llm.ainvoke([SystemMessage(content=sys), HumanMessage(content=msg)])
        verdict = _delta_text(resp).strip()
        if verdict and "COMPLETE" not in verdict.upper()[:12]:
            return verdict[:220]
        return ""
    except Exception:  # noqa: BLE001 — reflection is best-effort; never breaks the turn
        logger.exception("reflection failed")
        return ""


# ---- specialist roster (S11): a focused clinical lens per question domain -------
# A deterministic classifier picks a specialty and injects a concise EXPERT FRAMING
# (not specific medical claims) into the clinician's system prompt — the agent
# reasons like the right specialist, while grounding + the deterministic Rx safety
# engine are unchanged. Safety is never a function of this lens.
_SPECIALTIES: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("cardiology", ("heart", "cardiac", "chest pain", "blood pressure", "hypertension",
                    "ace inhibit", "beta block", "statin", "arrhythmia", " ecg", "angina", "heart failure"),
     "Frame this as a cardiology consult: weigh cardiovascular risk, cardiac history and vitals, and "
     "any cardiac effects/contraindications of the drugs involved; escalate red-flag cardiac symptoms."),
    ("endocrinology", ("diabet", "hba1c", "insulin", "metformin", "thyroid", "glucose", "hypoglyc", "hyperglyc"),
     "Frame this as an endocrinology consult: consider glycaemic control, renal function before certain "
     "agents, and endocrine interactions; flag hypo/hyperglycaemia risk."),
    ("nephrology", ("kidney", "renal", "egfr", "creatinine", "potassium", "dialysis", "nephro"),
     "Frame this as a nephrology consult: check renal function and electrolytes (especially potassium) "
     "before dosing renally-cleared or nephrotoxic drugs; flag AKI/CKD concerns."),
    ("respiratory", ("asthma", "copd", "breath", "wheez", "respirat", "inhaler", "pneumonia", "oxygen"),
     "Frame this as a respiratory consult: consider airway/oxygenation, inhaler therapy, and infective "
     "vs chronic causes; escalate respiratory distress."),
    ("infectious disease", ("infect", "antibiotic", "sepsis", "fever", "culture", "amoxicillin",
                            "penicillin", "resistance", "antimicrob"),
     "Frame this as an infectious-disease consult: consider likely organisms, allergy/resistance, and "
     "antimicrobial stewardship; flag sepsis red flags."),
    ("paediatrics", ("child", "infant", "baby", "paediatric", "pediatric", "immunis", "immuniz",
                     "vaccin", "growth", "weight-for-age"),
     "Frame this as a paediatric consult: weight-based dosing, immunisation schedule and growth, and "
     "age-appropriate safety; involve the guardian."),
    ("mental health", ("depress", "anxiety", "suicid", "mental health", "ssri", "psychiat", " mood"),
     "Frame this as a mental-health consult: assess risk sensitively and safety-net; consider SSRI "
     "cautions/interactions; escalate any self-harm risk urgently."),
)


def _detect_specialty(question: str) -> tuple[str, str] | None:
    """Return (specialty, lens) for a clinical question, or None. Deterministic."""
    q = (question or "").lower()
    for domain, kws, lens in _SPECIALTIES:
        if any(k in q for k in kws):
            return domain, lens
    return None


_SOURCE_RE = re.compile(r"\[source:\s*([A-Za-z]+)/([A-Za-z0-9._-]+)\]")


def _context_citations(context_text: str) -> list[dict[str, str]]:
    """Unique [source: Type/id] refs from the context, as citation chips."""
    out: dict[str, dict[str, str]] = {}
    for rt, rid in _SOURCE_RE.findall(context_text or ""):
        ref = f"{rt}/{rid}"
        out.setdefault(ref, {"ref": ref, "resource_type": rt, "id": rid})
    return list(out.values())


def _context_widgets(context_text: str) -> list[dict[str, Any]]:
    """Deterministically derive generative-UI widgets from the grounded context
    block (used on the tool-free fast path, where the model can't call
    render_widget): a safety-alert from the SAFETY FLAGS line and record-links
    from problems/medications/allergies."""
    lines = [ln.strip().lstrip("-").strip() for ln in (context_text or "").splitlines()]
    out: list[dict[str, Any]] = []

    def _section(label: str) -> str | None:
        for s in lines:
            if s.lower().startswith(label.lower()):
                return s[len(label):].lstrip(": ").rstrip(".")
        return None

    flags = _section("SAFETY FLAGS (deterministic)")
    if flags:
        items = [f.strip() for f in flags.split(";") if f.strip()]
        if items:
            sev = "block" if any(("high-risk" in i.lower() or "critical" in i.lower()) for i in items) else "warn"
            out.append({"id": "w_ctx_flags", "kind": "safety-alert", "title": "Safety flags",
                        "data": {"severity": sev, "items": items}})

    links: list[dict[str, str]] = []
    for label in ("Active problems", "Active medications", "Allergies"):
        sec = _section(label)
        if not sec:
            continue
        for item in sec.split(";"):
            m = _SOURCE_RE.search(item)
            if m:
                text = _SOURCE_RE.sub("", item).strip().rstrip(" .")
                if text:
                    links.append({"label": text[:80], "ref": f"{m.group(1)}/{m.group(2)}"})
    if links:
        out.append({"id": "w_ctx_links", "kind": "record-links", "title": "In your record",
                    "data": {"items": links[:12]}})
    return out


# Live reasoning trace (P2c "think-itself"): as the agent invokes tools, we stream
# a short human-readable status so the person SEES it working through the record.
_RECORD_NOUN = {
    "get_patient_summary": "the basics", "get_record_overview": "the whole record",
    "get_conditions": "conditions", "get_medications": "medications", "get_allergies": "allergies",
    "get_vitals": "vitals", "get_lab_results": "lab results", "get_immunizations": "immunisations",
    "get_encounters": "visit history", "get_clinical_notes": "clinical notes",
    "get_procedures": "procedures", "get_appointments": "appointments",
    "get_family_history": "family history", "get_social_history": "lifestyle & social history",
}
_ACTION_PHRASE = {
    "screen_medication": "Screening the medicine for interactions",
    "draft_prescription": "Preparing the prescription for sign-off",
    "web_search": "Searching up-to-date medical references",
    "present_card": "Putting together a summary", "render_widget": "Preparing a visual",
    "request_refill": "Preparing the refill", "book_appointment": "Setting up the booking",
    "start_video": "Getting the video visit ready", "remember": "Noting that for next time",
}


def _tool_status(name: str, audience: str) -> str | None:
    """A short 'what I'm doing now' line for a tool call, in the persona's voice."""
    if name in _RECORD_NOUN:
        noun = _RECORD_NOUN[name]
        return f"Looking at your {noun}" if audience == "patient" else f"Reviewing {noun}"
    return _ACTION_PHRASE.get(name)


def _tool_names(message: Any) -> list[str]:
    """Tool-call names on an AI message (LangChain dict-or-object tool_calls)."""
    out: list[str] = []
    for tc in getattr(message, "tool_calls", None) or []:
        nm = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
        if nm:
            out.append(nm)
    return out


def _delta_text(chunk: Any) -> str:
    """Pull text from an AIMessageChunk whose content may be a str or a block list."""
    content = getattr(chunk, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


_TOOL_LEAK_KEYS = re.compile(
    r'"(tool|tool_name|tool_call|name|function|action|arguments|parameters|tool_input|input)"\s*:',
    re.IGNORECASE,
)


def _looks_like_tool_leak(text: str) -> bool:
    """True when a model's 'answer' is actually a leaked/hallucinated tool call rather
    than prose. Some open models (e.g. Qwen on Groq) emit a JSON function-call as TEXT
    when told NOT to use tools; streamed verbatim it shows the user raw
    '{"tool": "get_record_overview", "arguments": {}}' instead of an answer. We detect
    that shape so a tool-free synthesis can discard it and fall back to a grounded,
    deterministic answer — the user never sees the machine JSON."""
    s = (text or "").strip()
    if not s:
        return False
    # Unwrap a ```json … ``` fence if the model wrapped the call in one.
    s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
    s = re.sub(r"\s*```$", "", s).strip()
    if not (s.startswith("{") or s.startswith("[")):
        return False  # prose never starts with a JSON brace
    return bool(_TOOL_LEAK_KEYS.search(s[:500]))


async def _synth_answer(llm: Any, msgs: list[Any], budget: float, on_usage) -> str:  # noqa: ANN001
    """Run a bounded, tool-free synthesis and return the answer text, or "" if the model
    produced nothing usable OR leaked a tool-call as text. BUFFERED (not streamed live)
    on purpose: some providers emit a hallucinated tool-call as their whole 'answer', so
    we must inspect the complete text before any of it reaches the client — streaming it
    token-by-token would put raw JSON on screen before we could tell it was garbage.
    Propagates asyncio.TimeoutError to the caller so a slow run is handled as a timeout."""
    buf: list[str] = []
    async with asyncio.timeout(budget):
        async for chunk in llm.astream(msgs):
            on_usage(chunk)
            d = _delta_text(chunk)
            if d:
                buf.append(d)
    text = "".join(buf).strip()
    if not text or _looks_like_tool_leak(text):
        return ""
    return text


_GROUNDED_SYNTH_NUDGE = (
    "\n\nAnswer the question ENTIRELY from the CURRENT PATIENT CONTEXT above — do NOT call or "
    "mention tools, and do NOT output JSON. Reuse the [source: …] citations exactly as given. If the "
    "answer is not in the context, say plainly what you would need to check."
)


def _grounded_synth_messages(audience: str, locale: str, context: str,
                             turn_messages: list[dict[str, str]], question: str) -> list[Any]:
    """Messages for a grounded, tool-free synthesis of the current turn from the
    pre-loaded cited context — the shared recipe behind both the quota fallback and
    the tool-leak recovery. The system prompt forbids tools/JSON so an open model is
    steered toward prose (and _synth_answer discards it if it leaks anyway)."""
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
    msgs: list[Any] = [SystemMessage(content=build_system_prompt(audience, locale, context) + _GROUNDED_SYNTH_NUDGE)]
    for mm in (turn_messages or [{"role": "user", "content": question}]):
        msgs.append(HumanMessage(content=mm["content"]) if mm["role"] == "user"
                    else AIMessage(content=mm["content"]))
    return msgs


@router.post("/chat")
async def chat(
    body: ChatRequest,
    request: Request,
    principal: Annotated[Principal, Depends(require_user)],
) -> StreamingResponse:
    settings: Settings = request.app.state.settings
    message_id = f"msg_{uuid.uuid4().hex}"
    text_id = f"txt_{uuid.uuid4().hex}"
    question = _latest_user_text(body.messages)  # for the "no record found" message
    agent_messages = _to_agent_messages(body.messages)

    async def stream() -> AsyncIterator[str]:
        # Per-turn observability (S1/S4): time the turn, record which path answered
        # it and the shape of the work, and log one structured line at every exit —
        # the foundation for latency/cost dashboards. Never changes response behaviour.
        _t0 = time.monotonic()

        yield _sse({"type": "start", "messageId": message_id})
        yield _sse({"type": "text-start", "id": text_id})

        def _fail(msg: str) -> list[str]:
            return [
                _sse({"type": "text-delta", "id": text_id, "delta": msg}),
                _sse({"type": "text-end", "id": text_id}),
                _sse({"type": "finish"}),
                "data: [DONE]\n\n",
            ]

        mode = settings.agent_llm_mode
        missing_key = (
            (mode == "live" and not settings.anthropic_api_key)
            or (mode == "openai" and not settings.llm_openai_api_key)
        )
        if missing_key:
            for f in _fail("Agent is not configured (no model key)."):
                yield f
            return

        fhir_id = await resolve_patient_fhir_id(settings.fhir_base_url, body.patient_id)
        if not fhir_id:
            for f in _fail(f"No FHIR record found for patient {body.patient_id}."):
                yield f
            return

        sources: list[dict[str, Any]] = []
        proposals: list[dict[str, Any]] = []
        cards: list[dict[str, Any]] = []
        widgets: list[dict[str, Any]] = []
        # Grounding by construction: pre-load a compact, cited context snapshot via
        # core-api (best-effort — falls back to on-demand tools if unavailable).
        context_text = await build_patient_context(
            settings.core_api_base_url, request.headers.get("authorization"), body.patient_id
        )
        # The record-only context (no memory block) — used to derive citations/widgets
        # and as the resilient overview fallback if the model can't synthesise in time.
        record_context = context_text

        # Long-term memory (P2): recall durable preferences/context and inject them;
        # the agent persists new ones via the `remember` tool. Scope: a PATIENT's
        # notes follow the patient (across their sessions, key = patient_id); a
        # CLINICIAN's response-style notes follow the DOCTOR (across every patient
        # they view, key = clin:<subject>), so the two personas that share a patient
        # never bleed preferences into each other.
        _redis = getattr(request.app.state, "redis", None)
        mem_subject = body.patient_id if body.audience == "patient" else f"clin:{principal.subject}"
        _mem = render_memory_block(await recall_memory(_redis, mem_subject))
        if _mem:
            context_text = (context_text + "\n\n" + _mem) if context_text else _mem

        async def _remember(note: str) -> bool:
            return await remember_memory(_redis, mem_subject, note)

        # Server-owned thread (H0-S1): when a conversation_id is given, the SERVER is
        # the source of truth for the history — build the turn from the stored thread
        # + the newest user message, so the conversation survives a reload and the
        # client no longer needs to re-send it. Falls back to the client's messages
        # when there is no stored thread (e.g. the first turn).
        turn_messages = agent_messages
        _thread = await load_thread(_redis, body.conversation_id)
        if _thread:
            turn_messages = [*_thread, {"role": "user", "content": question}]

        # State tracked across the run so we can GUARANTEE an answer floor: every
        # 200 stream must carry at least one text-delta. A tool-heavy request (e.g.
        # "give me a full 360 profile") can otherwise finish with an empty final
        # assistant turn (recursion cap / token truncation / a trailing tool or
        # present_card call) and render a silent blank bubble.
        streamed = False  # at least one token was streamed to the client
        final_answer = ""  # last non-empty AI message content (non-streaming providers)
        errored = False  # an error note was already emitted as the reply
        timed_out = False
        token_total = 0  # LLM tokens used this turn (best-effort, from usage_metadata)
        answer_parts: list[str] = []  # assistant text this turn, for the server thread

        def _add_usage(obj: Any) -> None:
            """Fold an AI message/chunk's token usage into the turn total (best-effort;
            usage_metadata is cumulative per call, so the last value for a call wins)."""
            nonlocal token_total
            um = getattr(obj, "usage_metadata", None)
            if isinstance(um, dict):
                tot = um.get("total_tokens")
                if isinstance(tot, int) and tot > token_total:
                    token_total = tot

        async def _finish_log(path: str) -> None:
            """One structured line per turn + a PHI-free telemetry record: which path
            answered, how long, how much work, tokens, and on which provider — the raw
            material for the latency/cost dashboards (S4). Best-effort; never blocks."""
            provider = (
                "anthropic"
                if settings.agent_react_provider == "anthropic" and settings.anthropic_api_key
                else settings.agent_llm_mode
            )
            ms = int((time.monotonic() - _t0) * 1000)
            logger.info(
                "chat_turn path=%s audience=%s mode=%s ms=%d sources=%d tokens=%d "
                "streamed=%s timed_out=%s errored=%s loop_provider=%s",
                path, body.audience, body.mode, ms, len(sources), token_total,
                streamed, timed_out, errored, provider,
            )
            await record_turn(
                _redis, path=path, audience=body.audience, ms=ms, provider=provider,
                tokens=token_total, streamed=streamed, timed_out=timed_out, errored=errored,
            )
            # Persist the exchange to the server-owned thread — but not the proactive
            # greeting (agent-initiated, not a user turn), and only when a real answer
            # was produced (never store an orphan user turn on an error/empty run).
            answer = ("".join(answer_parts) or final_answer).strip()
            if path != "proactive" and answer:
                await append_turn(_redis, body.conversation_id, question, answer)

        # PROACTIVE (P5): an agent-authored grounded greeting/nudge on portal-open —
        # not a reply to a user turn. Synthesise a warm, brief greeting from the
        # context + memory, then always render the safety/record widgets + a few
        # next-best-actions so the person lands on something useful and actionable.
        if body.mode == "proactive":
            try:
                from langchain_core.messages import HumanMessage, SystemMessage
                # A MINIMAL, tool-free prompt: the full persona prompt lists tools, and
                # a direct (toolless) call then makes the model emit a JSON tool-plan
                # instead of prose. Keep only the tone + grounded context here.
                tone = (
                    "You are a warm, reassuring health concierge speaking DIRECTLY to a patient in "
                    "plain, kind language (second person, 'you'). You never diagnose or replace a doctor."
                    if body.audience == "patient"
                    else "You are a concise clinical assistant giving a doctor a proactive brief."
                )
                sys_prompt = (
                    tone + "\n\n" + context_text +
                    "\n\nGreet this person warmly (by first name if the context gives one) in 2-4 short lines: "
                    "surface only the MOST important thing(s) right now — a safety flag, an overdue item, or a "
                    "result worth explaining — then invite them to ask. Reuse any [source: …] citations. Reply "
                    "with ONLY the greeting prose — do NOT output JSON, a 'thought', or tool calls."
                )
                pro_msgs: list[Any] = [
                    SystemMessage(content=sys_prompt),
                    HumanMessage(content="Greet me and tell me what I should know or do today."),
                ]
                llm = build_chat_llm(settings, streaming=True)
                async with asyncio.timeout(settings.agent_run_timeout_seconds):
                    async for chunk in llm.astream(pro_msgs):
                        _add_usage(chunk)
                        d = _delta_text(chunk)
                        if d:
                            streamed = True
                            yield _sse({"type": "text-delta", "id": text_id, "delta": d})
            except Exception:  # noqa: BLE001
                logger.exception("proactive greeting failed")
            if not streamed:
                yield _sse({"type": "text-delta", "id": text_id,
                            "delta": "Hello — I'm here to help you understand your health record. Ask me anything."})
            for w in _context_widgets(context_text):
                yield _sse({"type": "data-widget", "widget": w})
            yield _sse({"type": "data-widget", "widget": {
                "id": "w_nba", "kind": "next-best-action", "title": "",
                "data": {"actions": [
                    {"id": "Explain my most recent result in simple terms.", "label": "Explain my results"},
                    {"id": "Am I due for any vaccinations, screenings or follow-ups?", "label": "What am I due for?"},
                    {"id": "What medications am I taking, and what are they for?", "label": "My medications"},
                ]}}})
            cites = _context_citations(context_text)
            if cites:
                yield _sse({"type": "data-citations", "data": cites})
            yield _sse({"type": "text-end", "id": text_id})
            yield _sse({"type": "finish"})
            yield "data: [DONE]\n\n"
            await _finish_log("proactive")
            return

        # FAST PATH — a broad "overview / 360 / full profile" is synthesised directly
        # from the pre-loaded, cited context in ONE streamed LLM call (no tool loop).
        # A proper agent answers from what it already has; the read tools are for
        # drilling into a specific domain, not for crawling all 14 on an overview.
        # This is fast (~5-15s), streams token-by-token, and stays grounded/cited.
        if record_context and _is_broad_overview(question):
            # A broad overview is bounded to ~45s here: one streamed synthesis pass is
            # plenty, and a slow model must NOT be allowed to run out the whole budget
            # only to then trigger the tool crawl. On any miss we present the context
            # directly (below) — so an overview always answers fast and grounded.
            synth_budget = min(45.0, settings.agent_run_timeout_seconds)
            try:
                from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

                sys_prompt = build_system_prompt(body.audience, body.locale, context_text) + (
                    "\n\nThe user asked for an overview / full profile. Write it ENTIRELY from the "
                    "CURRENT PATIENT CONTEXT above — do NOT call or mention tools. Lead with any "
                    "SAFETY FLAGS, then organise clearly into short sections/bullets, and reuse the "
                    "[source: …] citations exactly as given. Be concise and clinical."
                )
                msgs: list[Any] = [SystemMessage(content=sys_prompt)]
                for m in turn_messages:
                    msgs.append(
                        HumanMessage(content=m["content"]) if m["role"] == "user"
                        else AIMessage(content=m["content"])
                    )
                llm = build_chat_llm(settings, streaming=True)
                # Buffered + validated: an open model told "don't use tools" can still
                # emit a hallucinated tool-call as its whole answer. We inspect the full
                # text first so raw '{"tool": …}' JSON never reaches the chat; on a leak
                # (or empty) this returns "" and the deterministic overview below runs.
                synth = await _synth_answer(llm, msgs, synth_budget, _add_usage)
                if synth:
                    streamed = True
                    answer_parts.append(synth)
                    yield _sse({"type": "text-delta", "id": text_id, "delta": synth})
                else:
                    logger.warning("overview synthesis produced no usable answer (empty/tool-leak); "
                                   "using deterministic context overview")
            except (TimeoutError, asyncio.TimeoutError):
                timed_out = True
                logger.warning("overview synthesis exceeded %ss; using context-derived overview", synth_budget)
            except Exception:  # noqa: BLE001 — resilient fallback below
                logger.exception("overview synthesis failed; using context-derived overview")
            # Resilient answer: if the model produced nothing (slow / unavailable),
            # stream the pre-loaded cited context itself — a grounded 360 built without
            # the model. A broad overview ALWAYS answers here; it never falls into the
            # multi-tool crawl, which reliably blows the time budget on a whole-record ask.
            if not streamed:
                fallback = _overview_from_context(record_context, body.audience)
                if fallback:
                    streamed = True
                    answer_parts.append(fallback)
                    yield _sse({"type": "text-delta", "id": text_id, "delta": fallback})
            cites = _context_citations(record_context)
            if cites:
                yield _sse({"type": "data-citations", "data": cites})
            # Generative UI: derive widgets deterministically from the grounded context
            # so an overview always renders rich components (safety alert, record links).
            for w in _context_widgets(record_context):
                yield _sse({"type": "data-widget", "widget": w})
            yield _sse({"type": "text-end", "id": text_id})
            yield _sse({"type": "finish"})
            yield "data: [DONE]\n\n"
            await _finish_log("overview")
            return

        # ACTION FAST PATH — a clear patient refill/book/video request is answered
        # INSTANTLY with a Confirm card, skipping the (slow, multi-round-trip) tool
        # loop. The model still only proposes; the card commits nothing until the
        # patient taps it (P3 invariant). Clinical-nuance phrasing defers to the agent.
        if body.audience == "patient":
            action = _detect_patient_action(question, record_context)
            if action is not None:
                widget, reply = _action_widget(action)
                answer_parts.append(reply)
                yield _sse({"type": "text-delta", "id": text_id, "delta": reply})
                yield _sse({"type": "data-widget", "widget": widget})
                yield _sse({"type": "text-end", "id": text_id})
                yield _sse({"type": "finish"})
                yield "data: [DONE]\n\n"
                await _finish_log("action")
                return

        # PLANNER (S5): for a genuinely multi-part ask, decompose it into a short
        # ordered plan and stream it as a plan-steps widget BEFORE working — the
        # visible "think-itself: plan, then do". Best-effort and bounded; the ReAct
        # agent below still does the actual, grounded, safety-checked work.
        plan_steps: list[str] = []
        if _is_multipart(question):
            plan_steps = await _make_plan(settings, question)
            if len(plan_steps) >= 2:
                yield _sse({"type": "data-widget", "widget": {
                    "id": "w_plan", "kind": "plan-steps", "title": "My plan",
                    "data": {"steps": [{"label": s} for s in plan_steps]}}})
            else:
                plan_steps = []

        # SPECIALIST ROSTER (S11): for a clinician's domain question, inject a focused
        # expert lens into the system prompt and show which specialist we're consulting
        # as. Grounding + the deterministic Rx-safety engine are unchanged by this.
        react_context = context_text
        if body.audience != "patient":
            specialty = _detect_specialty(question)
            if specialty:
                domain, lens = specialty
                react_context = (react_context + "\n\nSPECIALIST LENS — " + lens) if react_context else ("SPECIALIST LENS — " + lens)
                yield _sse({"type": "data-status", "text": f"Consulting as {domain}"})

        # ReAct on the preferred loop provider (Claude when configured).
        _can_fallback = settings.agent_react_provider == "anthropic" and bool(settings.anthropic_api_key)
        agent = build_agent(
            settings, fhir_id, sources, proposals,
            audience=body.audience, cards=cards, widgets=widgets,
            remember_fn=_remember, locale=body.locale, context_text=react_context,
        )
        try:
            # Provider-agnostic streaming. We ask for BOTH "messages" (token stream)
            # and "values" (full state per step). Anthropic streams the answer token
            # by token via "messages"; OpenAI-compatible providers (e.g. Groq) do NOT
            # stream the post-tool-call answer through langgraph, so those token
            # chunks are empty — for them we fall back to the final message content
            # from "values". `streamed` guards against emitting both (no duplication).
            announced: set[str] = set()  # tool names we've already narrated
            async with asyncio.timeout(settings.agent_run_timeout_seconds):
                async for mode, data in agent.astream(
                    {"messages": turn_messages or [{"role": "user", "content": question}]},
                    stream_mode=["messages", "values"],
                    config={"recursion_limit": settings.agent_recursion_limit},
                ):
                    if mode == "messages":
                        token = data[0]
                        if token.__class__.__name__ == "AIMessageChunk":
                            _add_usage(token)
                            delta = _delta_text(token)
                            if delta:
                                streamed = True
                                answer_parts.append(delta)
                                yield _sse({"type": "text-delta", "id": text_id, "delta": delta})
                    elif mode == "values":
                        msgs = data.get("messages", []) if isinstance(data, dict) else []
                        # Live reasoning trace: narrate any newly-called tools as the
                        # agent works, so a multi-step answer shows its thinking.
                        for m in msgs:
                            for nm in _tool_names(m):
                                if nm not in announced:
                                    announced.add(nm)
                                    label = _tool_status(nm, body.audience)
                                    if label:
                                        yield _sse({"type": "data-status", "text": label})
                        if msgs and getattr(msgs[-1], "type", "") == "ai":
                            _add_usage(msgs[-1])
                            text = _delta_text(msgs[-1])
                            if text:
                                final_answer = text
        except (TimeoutError, asyncio.TimeoutError):
            timed_out = True
            logger.warning("agent run exceeded %ss", settings.agent_run_timeout_seconds)
        except Exception as exc:  # noqa: BLE001 — never leak a stack trace to the UI
            m = str(exc).lower()
            is_quota = any(s in m for s in ("usage limit", "regain access", "rate limit",
                                            "429", "credit balance", "insufficient", "quota", "overloaded"))
            # QUOTA-RESILIENCE fallback: if the preferred loop provider is capped BEFORE
            # anything was produced, answer from the pre-loaded cited context via a
            # grounded DIRECT SYNTHESIS on the configured model (Groq) — no tool loop,
            # because Groq's Qwen is unreliable at function-calling. The answer is
            # grounded in the record context; a domain not in it is answered honestly.
            if (is_quota and _can_fallback and record_context and not streamed
                    and not final_answer and not widgets and not proposals and not sources and not cards):
                logger.warning("react: preferred provider capped — grounded synthesis fallback on the configured model")
                yield _sse({"type": "data-status", "text": "Switching to the backup model…"})
                try:
                    fb_msgs = _grounded_synth_messages(body.audience, body.locale, react_context,
                                                       turn_messages, question)
                    fb_llm = build_chat_llm(settings, streaming=True)
                    # Buffered + validated (see _synth_answer): the backup model is the
                    # same open model that can leak a tool-call as text, so we must not
                    # stream it blind.
                    synth = await _synth_answer(fb_llm, fb_msgs, settings.agent_run_timeout_seconds, _add_usage)
                    if synth:
                        streamed = True
                        answer_parts.append(synth)
                        yield _sse({"type": "text-delta", "id": text_id, "delta": synth})
                        for c in ([] if sources else _context_citations(record_context)):
                            sources.append(c)  # so the tail emits the grounding chips
                except Exception:  # noqa: BLE001 — fallback is best-effort
                    logger.exception("fallback synthesis failed")
            if not streamed and not errored:
                logger.exception("agent run failed")
                if is_quota:
                    note = (
                        "\n\n[The AI assistant is temporarily unavailable — the language-model "
                        "service usage limit has been reached. Record viewing, search and "
                        "prescription safety are unaffected. Please try the assistant again later.]"
                    )
                else:
                    note = "\n\n[The assistant hit an error. Please retry.]"
                errored = True
                yield _sse({"type": "text-delta", "id": text_id, "delta": note})

        # LEAK / EMPTY RECOVERY — an open model (Qwen) can END the tool loop with a
        # hallucinated tool-call as its 'final answer' (raw '{"tool": …}' JSON) instead
        # of prose, or with nothing usable. Never surface that: answer from the grounded
        # context via a tool-free synthesis; if even that leaks, drop it so the clean
        # floor message stands rather than machine JSON.
        if (not streamed and not errored and not timed_out and record_context
                and (not final_answer or _looks_like_tool_leak(final_answer))):
            leaked_answer = bool(final_answer)
            try:
                rec_msgs = _grounded_synth_messages(body.audience, body.locale, react_context,
                                                    turn_messages, question)
                synth = await _synth_answer(build_chat_llm(settings, streaming=True), rec_msgs,
                                            settings.agent_run_timeout_seconds, _add_usage)
                if synth:
                    final_answer = synth
                    for c in ([] if sources else _context_citations(record_context)):
                        sources.append(c)  # so the tail emits the grounding chips
                elif leaked_answer:
                    final_answer = ""  # leak with no clean synthesis → let the floor speak
            except Exception:  # noqa: BLE001 — recovery is best-effort, never blocks the floor
                logger.exception("tool-leak recovery synthesis failed")
                if leaked_answer:
                    final_answer = ""

        # ANSWER FLOOR — the stream must never be silent. Priority: streamed tokens
        # (nothing to do) → non-streaming provider's final answer → a graceful
        # message so the user always sees something actionable.
        if not streamed and not errored:
            if final_answer and not _looks_like_tool_leak(final_answer):
                yield _sse({"type": "text-delta", "id": text_id, "delta": final_answer})
            else:
                if timed_out:
                    floor = (
                        "This is taking longer than expected. Please try again, or ask "
                        "about one thing at a time (for example your medications, "
                        "allergies, or latest results)."
                    )
                else:
                    floor = (
                        "I looked into the record but couldn't put together a full answer "
                        "in one go. Please try again, or ask about one area at a time — "
                        "medications, allergies, or recent results."
                    )
                if sources:
                    floor += f"\n\n(Reviewed {len(sources)} record source(s).)"
                yield _sse({"type": "text-delta", "id": text_id, "delta": floor})

        # REFLECT (S5): for a planned multi-part ask that answered cleanly, self-check
        # the answer against the plan and, only if a real step was missed, append a
        # short reflection (never re-answers, never fires when complete or on error).
        if plan_steps and streamed and not errored and not timed_out:
            gap = await _reflect(settings, plan_steps, "".join(answer_parts) or final_answer)
            if gap:
                yield _sse({"type": "text-delta", "id": text_id,
                            "delta": f"\n\n**On reflection —** one thing to add: {gap}"})

        yield _sse({"type": "text-end", "id": text_id})
        if sources:  # citation chips (FR-3.4): resources the tools read
            yield _sse({"type": "data-citations", "data": sources})
        if proposals:  # write-intent drafts → sign-off cards (04 §2.2)
            # Defence-in-depth: never forward a `block` verdict as a signable card,
            # even if one somehow reached the sink (the tool no longer stages them).
            safe = [p for p in proposals if p.get("verdict") != "block"]
            if safe:
                yield _sse({"type": "data-proposals", "data": safe})
        if cards:  # generative-UI summary cards (present_card) rendered by the client
            yield _sse({"type": "data-cards", "data": cards})
        for w in widgets:  # generative-UI widgets (render_widget) → client registry
            yield _sse({"type": "data-widget", "widget": w})
        yield _sse({"type": "finish"})
        yield "data: [DONE]\n\n"
        await _finish_log("react")

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "x-vercel-ai-ui-message-stream": "v1",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )

"""Deterministic emergency red-flag detector (safety is topology, not prompt).

Mirrors the discipline of the deterministic PHI guard (`safety_guards.py`) and the
deterministic context safety flags: pure keyword / grounded-context matching — NO
model judgement — so the same input always escalates the same way and the detector
itself can never become a source of failure on a turn.

`detect_emergency` runs on the fast path in the chat router. When the user's
message OR the pre-loaded grounded context contains an emergency red flag, it
returns an ADDITIVE escalation spec (severity, a short grounded reason, and an
audience-appropriate action). It NEVER diagnoses and NEVER blocks or replaces the
normal answer — it triages / escalates only, alongside whatever the agent says.

Design choices that keep it conservative and PHI-safe:

- ACUTE SYMPTOMS (chest pain, stroke/FAST, breathing, anaphylaxis, sepsis,
  self-harm) are read from the USER'S MESSAGE, not the chart — so a chronic
  condition sitting in the record (e.g. "Angina" in the problem list) never
  self-triggers an escalation on an unrelated turn.
- The CHART contributes exactly two things: (a) a result the deterministic brief
  already flagged CRITICAL is itself an escalation trigger, and (b) known cardiac
  history is a RISK MODIFIER that, together with chest pain in the message,
  escalates.
- SELF-HARM is matched only on explicit first-person crisis phrases in the
  message, never on the record — so a negated / historical chart mention
  ("denies suicidal ideation") can never fire it. It always routes to a
  supportive, helpline-framed response, never a clinical one.

Sri Lanka context: the patient actions are the real national ones — **1990
Suwaseriya** (national ambulance) and the nearest **ETU** (Emergency Treatment
Unit); self-harm adds the **1926** National Mental Health Helpline (and Sri Lanka
Sumithrayo). Clinician actions escalate to the ETU / on-call / rapid-response team.
"""

from __future__ import annotations

import re

# A result the deterministic brief already flagged critical. `\bcritical\b` matches
# the "(CRITICAL)" the context renders and phrases like "critical potassium", but
# NOT the allergy "criticality" value (the trailing "i" defeats the word boundary).
_CRITICAL_RE = re.compile(r"\bcritical\b", re.IGNORECASE)

# ---- red-flag vocabularies (conservative, documented) -----------------------

# Explicit self-harm / suicidal ideation — first-person crisis phrasing ONLY, so a
# clinician's analytical "assess suicide risk" query and a negated chart note never
# fire it. Checked against the message only.
_SELF_HARM = (
    "kill myself", "killing myself", "want to kill myself", "going to kill myself",
    "end my life", "ending my life", "take my own life", "end it all",
    "want to die", "wanna die", "wish i was dead", "wish i were dead",
    "don't want to live", "dont want to live", "don't want to be alive",
    "dont want to be alive", "no reason to live", "better off dead",
    "hurt myself", "harm myself", "harming myself", "cut myself",
    "self-harm", "self harm", "i'm suicidal", "im suicidal", "i am suicidal",
    "feeling suicidal", "feel suicidal", "having suicidal thoughts",
    "suicidal thoughts", "thoughts of suicide", "thinking of suicide",
    "thinking about suicide",
)

# Anaphylaxis / severe allergic reaction.
_ANAPHYLAXIS = (
    "anaphylax", "anaphylactic", "severe allergic reaction",
    "throat closing", "throat is closing", "throat closing up",
    "throat tightening", "closing up my throat",
)
# Swelling that, with airway/breathing involvement, means anaphylaxis.
_SWELLING = ("swollen tongue", "tongue swelling", "swelling tongue",
             "swollen lips", "lips swelling", "swollen throat", "face swelling",
             "swelling of my face")
_AIRWAY = ("throat", "breathe", "breathing", "swallow", "wheez")

# Chest pain wording + the warning features / risk that make it an emergency.
_CHEST = ("chest pain", "chest tightness", "chest pressure", "pain in my chest",
          "pain in the chest", "tightness in my chest", "tightness in the chest",
          "pressure in my chest", "pressure in the chest", "crushing chest",
          "chest is tight", "chest feels tight", "chest hurts")
_CARDIAC_FEATURE = {
    "short of breath": "breathlessness", "shortness of breath": "breathlessness",
    "can't breathe": "breathlessness", "cant breathe": "breathlessness",
    "cannot breathe": "breathlessness", "breathless": "breathlessness",
    "sweating": "sweating", "sweaty": "sweating", "cold sweat": "sweating",
    "clammy": "sweating", "left arm": "pain spreading to the arm",
    "arm pain": "pain spreading to the arm", "into my arm": "pain spreading to the arm",
    "jaw": "pain spreading to the jaw", "radiat": "spreading pain",
    "nausea": "nausea", "vomit": "nausea", "dizzy": "dizziness",
    "faint": "feeling faint", "crushing": "a crushing quality",
    "severe": "severe pain", "worst": "the worst pain",
}
# Known cardiac history in the chart — a risk modifier for chest pain (not itself a
# trigger). Read from the grounded record context only.
_CARDIAC_HISTORY = ("myocardial", "coronary", "angina", "ischaem", "ischemic",
                    "heart failure", "arrhythmia", "atrial fibrillation",
                    " cardiac", "cardiomyopathy", "stent", "cabg")

# Stroke / FAST signs.
_STROKE = ("stroke", "face drooping", "facial droop", "face is drooping",
           "slurred speech", "slurring", "can't speak", "cant speak",
           "cannot speak", "weakness on one side", "weak on one side",
           "one side of my body", "one-sided weakness", "numb on one side",
           "arm went weak", "arm feels weak", "drooping face", "can't move my arm")

# Severe breathing difficulty (strong phrases fire directly).
_BREATHING = ("can't breathe", "cant breathe", "cannot breathe", "can not breathe",
              "struggling to breathe", "trouble breathing", "difficulty breathing",
              "hard to breathe", "can't catch my breath", "cant catch my breath",
              "gasping", "choking", "respiratory distress", "turning blue",
              "blue lips", "suffocating", "can't get air", "cant get air")
# Milder breathlessness needs a severity qualifier to escalate.
_BREATH_MILD = ("short of breath", "shortness of breath", "breathless")
_BREATH_QUALIFIER = ("severe", "severely", "sudden", "suddenly", "can't", "cant",
                     "cannot", "worst", "really bad", "very bad", "badly")

# Sepsis — the word itself, or fever paired with hypotension (per the brief).
_SEPSIS = ("sepsis", "septic shock", "septic")
_FEVER = ("fever", "high temperature", "burning up", "very hot", "febrile")
_HYPOTENSION = ("low blood pressure", "hypotension", "bp is low", "blood pressure is low",
                "pressure dropped", "passing out", "about to pass out", "collapsing",
                "collapsed", "can't stay awake")


def _has(text: str, needles: tuple[str, ...]) -> str | None:
    """First needle found in `text` (already lowercased), or None."""
    for n in needles:
        if n in text:
            return n
    return None


def _p(audience: str, patient_text: str, clinician_text: str) -> str:
    """Pick audience-appropriate wording. Anything but 'clinician' is patient-facing."""
    return clinician_text if audience == "clinician" else patient_text


def _patient_actions() -> list[dict[str, str]]:
    """The Sri Lanka patient emergency actions: call the national ambulance (a real
    `tel:` link) and find the nearest ETU (routes the phrasing to the agent)."""
    return [
        {"label": "Call 1990 Suwaseriya", "tel": "1990"},
        {"label": "Find my nearest ETU",
         "prompt": "Where is my nearest Emergency Treatment Unit (ETU), and how do I get there quickly?"},
    ]


def _clinician_actions(label: str = "Escalate to ETU / rapid response") -> list[dict[str, str]]:
    """A clinician escalate button — an explicit, audited action (wired client-side)."""
    return [{"label": label, "action": "escalate"}]


def _spec(*, severity: str, category: str, reason: str, title: str, spoken: str,
          note: str, actions: list[dict[str, str]], audience: str) -> dict:
    """Assemble the escalation spec. `widget` is the data payload the `escalation`
    widget renders; the top-level fields describe the spec for logs / callers."""
    return {
        "severity": severity,
        "category": category,
        "reason": reason,
        "title": title,
        "spoken": spoken,
        "audience": audience,
        "widget": {
            "severity": severity,
            "category": category,
            "reason": reason,
            "note": note,
            "actions": actions,
        },
    }


def _critical_label(context: str) -> str | None:
    """If the context carries a result flagged CRITICAL, return a short PHI-safe
    label for it (e.g. 'Serum potassium'), '' if critical but unnamed, or None if no
    critical result is present."""
    if not _CRITICAL_RE.search(context):
        return None
    for line in context.splitlines():
        s = line.strip().lstrip("-").strip()
        low = s.lower()
        if low.startswith("recent results:") or low.startswith("safety flags"):
            body = s.split(":", 1)[1] if ":" in s else s
            for seg in re.split(r";", body):
                if _CRITICAL_RE.search(seg):
                    name = re.sub(r"\s*\[source:[^\]]*\]", "", seg)
                    name = re.sub(r"\(critical\)", "", name, flags=re.IGNORECASE)
                    # Drop a leading "Critical result:" / "Critical:" label so the
                    # reason doesn't read "...flagged CRITICAL — Critical result: X".
                    name = re.sub(r"^\s*critical(\s+result)?\s*:\s*", "", name, flags=re.IGNORECASE)
                    name = re.sub(r"\s+", " ", name).strip(" .")
                    return name[:60]
    return ""


def detect_emergency(question: str, record_context: str, audience: str) -> dict | None:
    """Deterministically detect an emergency red flag in the user's message or the
    grounded record context. Returns an additive escalation spec, or None (the vast
    majority of turns). Pure and side-effect free; never diagnoses.
    """
    q = (question or "").lower()
    ctx = record_context or ""
    aud = audience or "patient"

    # 1) SELF-HARM (message only, most sensitive) — always a supportive, helpline
    #    framing, never clinical. Checked first so it owns the response.
    if _has(q, _SELF_HARM):
        if aud == "clinician":
            return _spec(
                severity="emergency", category="self-harm", audience=aud,
                reason="Message contains explicit self-harm / suicidal statements.",
                title="Self-harm risk — escalate",
                spoken="Red flag: explicit self-harm language — do not leave the patient "
                       "alone; escalate to on-call psychiatry / the crisis team now.",
                note="Explicit self-harm language — do not leave the patient unattended; "
                     "escalate to the mental-health crisis / on-call psychiatry team and "
                     "carry out a risk assessment.",
                actions=_clinician_actions("Escalate to on-call psychiatry"),
            )
        return _spec(
            severity="emergency", category="self-harm", audience=aud,
            reason="Your safety matters, and you don't have to face this alone.",
            title="You matter — help is available",
            spoken="I'm really glad you told me. You deserve support right now — please "
                   "reach out to someone who can help. You can call the 1926 mental-health "
                   "helpline any time.",
            note="If you're thinking about harming yourself, please talk to someone now. "
                 "Call the 1926 National Mental Health Helpline, or Sri Lanka Sumithrayo. "
                 "If you're in immediate danger, call 1990 Suwaseriya.",
            actions=[
                {"label": "Call 1926 (mental-health helpline)", "tel": "1926"},
                {"label": "Call 1990 Suwaseriya", "tel": "1990"},
            ],
        )

    # 2) CRITICAL LAB already flagged in the chart (context-derived, grounded).
    crit = _critical_label(ctx)
    if crit is not None:
        suffix = f" — {crit}" if crit else ""
        return _spec(
            severity="emergency", category="critical-lab", audience=aud,
            reason=_p(aud,
                      f"A recent result in your record is flagged critical{suffix}.",
                      f"A result in the chart is flagged CRITICAL{suffix}."),
            title="Critical result",
            spoken=_p(aud,
                      "One of your recent results is flagged as critical. This needs urgent "
                      "medical attention — please call 1990 Suwaseriya now, or go to the nearest ETU.",
                      "A result in the chart is flagged CRITICAL — consider immediate escalation."),
            note=_p(aud,
                    "This needs urgent, in-person care now. If someone is nearby, ask them to "
                    "help you get to the nearest Emergency Treatment Unit (ETU).",
                    "Deterministic red flag — consider immediate escalation to the ETU / on-call "
                    "/ rapid-response team and a focused assessment."),
            actions=_patient_actions() if aud != "clinician" else _clinician_actions(),
        )

    # 3) ANAPHYLAXIS / severe allergic reaction (message).
    if _has(q, _ANAPHYLAXIS) or (_has(q, _SWELLING) and _has(q, _AIRWAY)):
        return _spec(
            severity="emergency", category="anaphylaxis", audience=aud,
            reason=_p(aud,
                      "You've described a severe allergic reaction.",
                      "Message reports features of anaphylaxis / severe allergic reaction."),
            title="Severe allergic reaction",
            spoken=_p(aud,
                      "A severe allergic reaction is an emergency. Please call 1990 Suwaseriya "
                      "now, or go to the nearest ETU.",
                      "Red flag: anaphylaxis features — treat as an emergency and escalate immediately."),
            note=_p(aud,
                    "This needs urgent, in-person care now. If someone is nearby, ask them to "
                    "help you get to the nearest Emergency Treatment Unit (ETU).",
                    "Deterministic red flag — escalate immediately to the ETU / rapid-response team."),
            actions=_patient_actions() if aud != "clinician" else _clinician_actions(),
        )

    # 4) STROKE / FAST signs (message).
    if _has(q, _STROKE):
        return _spec(
            severity="emergency", category="stroke", audience=aud,
            reason=_p(aud,
                      "You've described signs that can mean a stroke (face, arm or speech "
                      "changes). Every minute matters.",
                      "Message reports FAST-positive stroke signs — time-critical."),
            title="Possible stroke — act fast",
            spoken=_p(aud,
                      "Signs of a stroke are an emergency and every minute counts. Please call "
                      "1990 Suwaseriya immediately.",
                      "Red flag: possible stroke (FAST) — activate the stroke pathway and escalate."),
            note=_p(aud,
                    "This is time-critical. Call 1990 Suwaseriya now, or get to the nearest ETU.",
                    "Deterministic red flag — time-critical; escalate to the ETU / stroke pathway now."),
            actions=_patient_actions() if aud != "clinician" else _clinician_actions(),
        )

    # 5) CHEST PAIN with warning features OR known cardiac history (message + chart).
    if _has(q, _CHEST):
        feat = None
        for kw, disp in _CARDIAC_FEATURE.items():
            if kw in q:
                feat = disp
                break
        cardiac_hist = _has(ctx.lower(), _CARDIAC_HISTORY) is not None
        if feat or cardiac_hist:
            because = feat or "cardiac risk factors in your record"
            return _spec(
                severity="emergency", category="cardiac", audience=aud,
                reason=_p(aud,
                          f"You've described chest pain with {because} — this can be serious "
                          "and needs urgent, in-person assessment.",
                          f"Message reports chest pain with {feat or 'cardiac risk in the chart'} "
                          "— consider a cardiac cause and escalate."),
                title="Possible cardiac emergency",
                spoken=_p(aud,
                          "Chest pain can be an emergency. Please call 1990 Suwaseriya now, or "
                          "go to the nearest ETU.",
                          "Red flag: chest pain with warning features — consider immediate escalation."),
                note=_p(aud,
                        "This needs urgent, in-person care now. If someone is nearby, ask them to "
                        "help you get to the nearest Emergency Treatment Unit (ETU).",
                        "Deterministic red flag — consider immediate escalation to the ETU / on-call "
                        "/ rapid-response team and a focused cardiac assessment."),
                actions=_patient_actions() if aud != "clinician" else _clinician_actions(),
            )

    # 6) SEVERE BREATHING DIFFICULTY (message).
    if _has(q, _BREATHING) or (_has(q, _BREATH_MILD) and _has(q, _BREATH_QUALIFIER)):
        return _spec(
            severity="emergency", category="breathing", audience=aud,
            reason=_p(aud,
                      "You've said you're having severe difficulty breathing.",
                      "Message reports severe respiratory difficulty."),
            title="Severe breathing difficulty",
            spoken=_p(aud,
                      "Severe trouble breathing is an emergency. Please call 1990 Suwaseriya now.",
                      "Red flag: severe breathing difficulty — escalate now."),
            note=_p(aud,
                    "This needs urgent, in-person care now. Call 1990 Suwaseriya, or get to the "
                    "nearest Emergency Treatment Unit (ETU).",
                    "Deterministic red flag — escalate immediately to the ETU / rapid-response team."),
            actions=_patient_actions() if aud != "clinician" else _clinician_actions(),
        )

    # 7) SEPSIS — the word, or fever with hypotension (message).
    if _has(q, _SEPSIS) or (_has(q, _FEVER) and _has(q, _HYPOTENSION)):
        return _spec(
            severity="emergency", category="sepsis", audience=aud,
            reason=_p(aud,
                      "You've described a fever together with signs of being very unwell "
                      "(such as low blood pressure or feeling faint).",
                      "Message reports fever with hypotension — screen for sepsis."),
            title="Possible serious infection",
            spoken=_p(aud,
                      "This could be a serious infection. Please seek urgent care now — call "
                      "1990 Suwaseriya, or go to the nearest ETU.",
                      "Red flag: fever with hypotension — screen for sepsis and escalate."),
            note=_p(aud,
                    "This needs urgent, in-person care now. If someone is nearby, ask them to "
                    "help you get to the nearest Emergency Treatment Unit (ETU).",
                    "Deterministic red flag — escalate to the ETU / rapid-response team and start "
                    "a sepsis screen."),
            actions=_patient_actions() if aud != "clinician" else _clinician_actions(),
        )

    return None

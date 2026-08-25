"""Patient-scoped clinical tools that read the FHIR record (04 §2.3).

A comprehensive read surface so a clinician can ask the chat for anything in the
record — demographics, problems, medications, allergies, vitals, labs, imaging,
immunisations, encounters, notes, procedures, appointments, family/social
history — plus a medication-safety screen for a drug under consideration.

Every read tool returns human-readable content AND records the FHIR resources it
touched into a shared `sources` list, so the chat layer can surface citation
chips linking back to the source resources (FR-3.4). In dev the tools hit HAPI
directly; in the target design they route through core-api's decision-checked
path so consent/authz apply (04 §1) — same tool surface.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from langchain_core.tools import BaseTool, tool

from app.rxsafety import screen as rx_screen

PHN_SYSTEM = "https://fhir.medagent.health.lk/id/phn"

# Generative-UI widget kinds the agent may render into the chat (P1). The web
# widget registry maps each kind → a React component.
_WIDGET_KINDS = {
    "summary", "safety-alert", "metric-trend", "stat-grid",
    "record-links", "next-best-action", "timeline",
}


class FhirClient:
    """Thin async FHIR reader scoped to one patient, accumulating citations."""

    def __init__(self, base_url: str, patient_fhir_id: str, sources: list[dict[str, Any]]):
        self._base = base_url.rstrip("/")
        self._pid = patient_fhir_id
        self._sources = sources

    async def search(self, resource_type: str, params: dict[str, str]) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self._base}/{resource_type}",
                params={**params, "_count": "50"},
                headers={"Accept": "application/fhir+json"},
            )
            resp.raise_for_status()
            bundle = resp.json()
        entries = [e["resource"] for e in bundle.get("entry", []) if "resource" in e]
        for r in entries:
            self.cite(r)
        return entries

    async def read(self, resource_type: str, rid: str) -> dict[str, Any] | None:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self._base}/{resource_type}/{rid}",
                headers={"Accept": "application/fhir+json"},
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            r = resp.json()
        self.cite(r)
        return r

    def cite(self, resource: dict[str, Any]) -> None:
        ref = f"{resource.get('resourceType')}/{resource.get('id')}"
        if not any(s["ref"] == ref for s in self._sources):
            self._sources.append(
                {"ref": ref, "resource_type": resource.get("resourceType"), "id": resource.get("id")}
            )


def _cc(cc: dict[str, Any] | None) -> str:
    if not cc:
        return "?"
    if cc.get("text"):
        return cc["text"]
    codings = cc.get("coding", [])
    if codings:
        c = codings[0]
        return c.get("display") or f"{c.get('system', '')}|{c.get('code', '')}"
    return "?"


def _qty(o: dict[str, Any]) -> str:
    vq = o.get("valueQuantity")
    if vq:
        return f"{vq.get('value', '?')} {vq.get('unit', '')}".strip()
    if "valueString" in o:
        return str(o["valueString"])
    if "valueCodeableConcept" in o:
        return _cc(o["valueCodeableConcept"])
    return "?"


def build_patient_tools(
    fhir_base_url: str,
    patient_fhir_id: str,
    sources: list[dict[str, Any]],
    proposals: list[dict[str, Any]] | None = None,
    cards: list[dict[str, Any]] | None = None,
    widgets: list[dict[str, Any]] | None = None,
    audience: str = "clinician",
) -> list[BaseTool]:
    """Build the read + screening tool belt for one patient, PERSONA-SCOPED.

    `proposals` accumulates write-intent drafts (draft_prescription) the chat layer
    surfaces as sign-off cards; `cards` accumulates generative-UI summary cards
    (present_card). Tool exposure is scoped by `audience`: a patient session gets
    read tools + present_card only (never medication screening or prescription
    drafting), a clinician session gets read tools + screen_medication +
    draft_prescription. This is a defence-in-depth boundary, not the only one —
    data access is patient-scoped by fhir_id regardless."""
    fhir = FhirClient(fhir_base_url, patient_fhir_id, sources)
    pid = patient_fhir_id
    drafts = proposals if proposals is not None else []
    card_sink = cards if cards is not None else []
    widget_sink = widgets if widgets is not None else []

    @tool
    async def get_patient_summary() -> str:
        """Personal details and identifiers: name, date of birth, gender, PHN, contact, blood group."""
        p = await fhir.read("Patient", pid)
        if not p:
            return "Patient not found."
        name = p.get("name", [{}])[0]
        full = " ".join(name.get("given", []) + [name.get("family", "")]).strip()
        phn = next((i["value"] for i in p.get("identifier", []) if i.get("system") == PHN_SYSTEM), "n/a")
        phone = next((t.get("value") for t in p.get("telecom", []) if t.get("system") == "phone"), "n/a")
        bg = await fhir.search("Observation", {"patient": pid, "code": "http://loinc.org|883-9"})
        blood = _qty(bg[0]) if bg else "not recorded"
        return (
            f"Name: {full or 'Unknown'} [source: Patient/{pid}]\n"
            f"PHN: {phn}\nDate of Birth: {p.get('birthDate', 'Not recorded')}\n"
            f"Gender: {p.get('gender', 'Not recorded')}\nPhone: {phone}\nBlood group: {blood}"
        )

    @tool
    async def get_conditions() -> str:
        """Active and past diagnoses / problems (ICD-10 coded)."""
        rows = await fhir.search("Condition", {"patient": pid})
        if not rows:
            return "No conditions recorded."
        return "Conditions:\n" + "\n".join(
            f"- {_cc(c.get('code'))} (clinical status: {_cc(c.get('clinicalStatus'))}, "
            f"verification: {_cc(c.get('verificationStatus'))}) [source: Condition/{c.get('id')}]"
            for c in rows
        )

    @tool
    async def get_medications() -> str:
        """Current and past medication requests (prescriptions), with dosage."""
        rows = await fhir.search("MedicationRequest", {"patient": pid})
        if not rows:
            return "No medications recorded."
        lines = []
        for m in rows:
            di = m.get("dosageInstruction", [])
            dose = f" — {di[0]['text']}" if di and di[0].get("text") else ""
            lines.append(
                f"- {_cc(m.get('medicationCodeableConcept'))} (status: {m.get('status', '?')})"
                f"{dose} [source: MedicationRequest/{m.get('id')}]"
            )
        return "Medications:\n" + "\n".join(lines)

    @tool
    async def get_allergies() -> str:
        """Known allergies and intolerances with criticality and reactions."""
        rows = await fhir.search("AllergyIntolerance", {"patient": pid})
        if not rows:
            return "No allergies recorded (NKDA not necessarily confirmed)."
        lines = []
        for a in rows:
            r = a.get("reaction", [])
            react = f", reaction: {_cc(r[0]['manifestation'][0])}" if r and r[0].get("manifestation") else ""
            lines.append(
                f"- {_cc(a.get('code'))} (criticality: {a.get('criticality', 'unknown')}{react}) "
                f"[source: AllergyIntolerance/{a.get('id')}]"
            )
        return "Allergies:\n" + "\n".join(lines)

    @tool
    async def get_vitals() -> str:
        """Recent vital-sign observations (HR, BP, temperature, weight, height, glucose)."""
        rows = await fhir.search("Observation", {"patient": pid, "category": "vital-signs", "_sort": "-date"})
        if not rows:
            return "No vital signs recorded."
        return "Vital signs:\n" + "\n".join(
            f"- {_cc(o.get('code'))}: {_qty(o)} ({o.get('effectiveDateTime', '')}) [source: Observation/{o.get('id')}]"
            for o in rows
        )

    @tool
    async def get_lab_results() -> str:
        """Laboratory results — lab observations and diagnostic reports with interpretations."""
        obs = await fhir.search("Observation", {"patient": pid, "category": "laboratory", "_sort": "-date"})
        reports = await fhir.search("DiagnosticReport", {"patient": pid, "_sort": "-date"})
        if not obs and not reports:
            return "No laboratory results recorded."
        out = []
        if obs:
            out.append("Lab observations:\n" + "\n".join(
                f"- {_cc(o.get('code'))}: {_qty(o)} "
                f"({'ABNORMAL' if o.get('interpretation') else 'normal/na'}) "
                f"[source: Observation/{o.get('id')}]"
                for o in obs
            ))
        if reports:
            out.append("Diagnostic reports:\n" + "\n".join(
                f"- {_cc(r.get('code'))} (status: {r.get('status', '?')}, issued {r.get('issued', '')}) "
                f"[source: DiagnosticReport/{r.get('id')}]"
                for r in reports
            ))
        return "\n\n".join(out)

    @tool
    async def get_immunizations() -> str:
        """Vaccination history."""
        rows = await fhir.search("Immunization", {"patient": pid, "_sort": "-date"})
        if not rows:
            return "No immunisations recorded."
        return "Immunisations:\n" + "\n".join(
            f"- {_cc(i.get('vaccineCode'))} (status: {i.get('status', '?')}, "
            f"{i.get('occurrenceDateTime', '')}) [source: Immunization/{i.get('id')}]"
            for i in rows
        )

    @tool
    async def get_encounters() -> str:
        """Visit / encounter history (consultations, admissions)."""
        rows = await fhir.search("Encounter", {"patient": pid, "_sort": "-date"})
        if not rows:
            return "No encounters recorded."
        return "Encounters:\n" + "\n".join(
            f"- {_cc(e.get('class')) if isinstance(e.get('class'), dict) else e.get('class', {}).get('code', '?')} "
            f"(status: {e.get('status', '?')}, {e.get('period', {}).get('start', '')}) [source: Encounter/{e.get('id')}]"
            for e in rows
        )

    @tool
    async def get_clinical_notes() -> str:
        """Clinical notes, letters and documents (visit summaries, referral letters)."""
        rows = await fhir.search("DocumentReference", {"patient": pid, "_sort": "-date"})
        if not rows:
            return "No clinical documents recorded."
        return "Documents:\n" + "\n".join(
            f"- {_cc(d.get('type'))} ({d.get('date', '')}, status: {d.get('status', '?')}) "
            f"[source: DocumentReference/{d.get('id')}]"
            for d in rows
        )

    @tool
    async def get_procedures() -> str:
        """Procedures performed (surgical and non-surgical)."""
        rows = await fhir.search("Procedure", {"patient": pid, "_sort": "-date"})
        if not rows:
            return "No procedures recorded."
        return "Procedures:\n" + "\n".join(
            f"- {_cc(p.get('code'))} (status: {p.get('status', '?')}, "
            f"{p.get('performedDateTime', '')}) [source: Procedure/{p.get('id')}]"
            for p in rows
        )

    @tool
    async def get_appointments() -> str:
        """Scheduled and past appointments / follow-ups."""
        rows = await fhir.search("Appointment", {"patient": pid, "_sort": "date"})
        if not rows:
            return "No appointments recorded."
        return "Appointments:\n" + "\n".join(
            f"- {a.get('start', '?')} (status: {a.get('status', '?')}, {_cc(a.get('appointmentType'))}) "
            f"[source: Appointment/{a.get('id')}]"
            for a in rows
        )

    @tool
    async def get_family_history() -> str:
        """Family medical history."""
        rows = await fhir.search("FamilyMemberHistory", {"patient": pid})
        if not rows:
            return "No family history recorded."
        lines = []
        for f in rows:
            conds = ", ".join(_cc(c.get("code")) for c in f.get("condition", [])) or "unspecified"
            lines.append(
                f"- {_cc(f.get('relationship'))}: {conds} [source: FamilyMemberHistory/{f.get('id')}]"
            )
        return "Family history:\n" + "\n".join(lines)

    @tool
    async def get_social_history() -> str:
        """Social history: smoking, alcohol, occupation and lifestyle observations."""
        rows = await fhir.search("Observation", {"patient": pid, "category": "social-history", "_sort": "-date"})
        if not rows:
            return "No social history recorded."
        return "Social history:\n" + "\n".join(
            f"- {_cc(o.get('code'))}: {_qty(o)} [source: Observation/{o.get('id')}]" for o in rows
        )

    @tool
    async def get_record_overview() -> str:
        """A one-shot overview counting what exists in the record across all domains —
        use this first when asked for a general picture, then drill in with the specific tools."""
        counts: list[str] = []
        for label, rt, params in [
            ("Problems", "Condition", {}),
            ("Medications", "MedicationRequest", {}),
            ("Allergies", "AllergyIntolerance", {}),
            ("Vitals", "Observation", {"category": "vital-signs"}),
            ("Labs", "Observation", {"category": "laboratory"}),
            ("Immunisations", "Immunization", {}),
            ("Encounters", "Encounter", {}),
            ("Documents", "DocumentReference", {}),
            ("Procedures", "Procedure", {}),
            ("Appointments", "Appointment", {}),
        ]:
            rows = await fhir.search(rt, {"patient": pid, **params})
            counts.append(f"- {label}: {len(rows)}")
        return "Record overview (counts by domain):\n" + "\n".join(counts)

    @tool
    async def screen_medication(proposed_drug: str) -> str:
        """Run the DETERMINISTIC Rx-safety engine for a medication the clinician is CONSIDERING.
        Use for any 'is X safe / can I prescribe X' question. The verdict (pass/warn/block) is
        computed by the engine, NOT by you — report it faithfully; you may explain it and add
        [general knowledge] context, but never override a `block`. Binding screening + mandatory
        e-sign-off run again at prescribe time (04)."""
        meds = await fhir.search("MedicationRequest", {"patient": pid, "status": "active"})
        allergies = await fhir.search("AllergyIntolerance", {"patient": pid})
        med_names = [_cc(m.get("medicationCodeableConcept")) for m in meds]
        alg_objs = [
            {"substance": _cc(a.get("code")), "criticality": a.get("criticality", "unknown")}
            for a in allergies
        ]
        v = rx_screen(proposed_drug, med_names, alg_objs)
        lines = [
            f"DETERMINISTIC Rx-SAFETY VERDICT for '{proposed_drug}': {v.verdict.upper()}",
            f"codes: {', '.join(v.codes) or 'none'}",
            f"dataset: {v.dataset_version}",
        ]
        if v.findings:
            lines.append("findings:")
            for f in v.findings:
                lines.append(f"  - [{f['severity']}] {f['code']}: {f['rationale']}")
        else:
            lines.append("findings: none — no interaction/allergy/dose issue detected by the engine.")
        med_src = "; ".join(
            f"{_cc(m.get('medicationCodeableConcept'))} [source: MedicationRequest/{m.get('id')}]" for m in meds
        ) or "none on record"
        alg_src = "; ".join(
            f"{_cc(a.get('code'))} [source: AllergyIntolerance/{a.get('id')}]" for a in allergies
        ) or "none on record"
        lines.append(f"screened against active meds: {med_src}")
        lines.append(f"screened against allergies: {alg_src}")
        lines.append(
            "Report the verdict verbatim (safe=pass / caution=warn / avoid=block). A `block` is a "
            "hard stop; a `warn` is overridable only with an explicit clinician reason at sign-off."
        )
        return "\n".join(lines)

    @tool
    async def draft_prescription(drug: str, dose_text: str = "") -> str:
        """Draft a prescription for the clinician to REVIEW AND SIGN. Use when the clinician
        asks to prescribe/start/give a medication. Runs the deterministic Rx-safety engine and
        stages the draft as a sign-off proposal — it does NOT commit anything. Report the verdict
        faithfully; if it is a block, tell the clinician it cannot be prescribed and suggest
        alternatives. Never say the drug has been prescribed."""
        meds = await fhir.search("MedicationRequest", {"patient": pid, "status": "active"})
        allergies = await fhir.search("AllergyIntolerance", {"patient": pid})
        v = rx_screen(
            drug,
            [_cc(m.get("medicationCodeableConcept")) for m in meds],
            [{"substance": _cc(a.get("code")), "criticality": a.get("criticality", "unknown")} for a in allergies],
        )
        # STRUCTURAL SAFETY: a `block` verdict is a hard stop. It is NEVER staged
        # as a signable proposal — the sign-off card only exists for pass/warn.
        # This makes "a blocked drug cannot be signed" a property of the code path,
        # not of the prompt (which a model could be talked around). core-api's
        # /proposals/commit re-screens as a second, independent backstop.
        if v.verdict == "block":
            return (
                f"BLOCKED: '{drug}' cannot be prescribed for this patient — the deterministic "
                f"Rx-safety engine returned BLOCK ({', '.join(v.codes) or 'safety rule'}). No sign-off "
                f"card was staged (a block is not overridable). Tell the clinician clearly and offer a "
                f"safer alternative."
            )
        drafts.append({
            "kind": "prescription",
            "drug": drug,
            "dose_text": dose_text,
            "verdict": v.verdict,
            "codes": v.codes,
            "findings": v.findings,
        })
        return (
            f"Drafted prescription: {drug} {dose_text}. Deterministic safety verdict: "
            f"{v.verdict.upper()} ({', '.join(v.codes) or 'no issues'}). A sign-off card has been "
            f"staged for the clinician to review and sign. Present the verdict (a WARN needs an explicit "
            f"override reason at sign-off). Do NOT claim it is prescribed — the clinician must sign."
        )

    @tool
    async def present_card(title: str, points: str, tone: str = "info") -> str:
        """Show the patient a clear visual SUMMARY CARD alongside your reply. Use once
        when explaining a result, medicine, or condition. `title` is a short heading;
        `points` is 2–4 key takeaways separated by ' | ' (pipe); `tone` is one of
        good | warn | urgent | info. This supplements your written answer — still reply
        normally in plain language."""
        pts = [p.strip() for p in points.split("|") if p.strip()][:4]
        t = tone if tone in {"good", "warn", "urgent", "info"} else "info"
        card_sink.append({"kind": "summary", "tone": t, "title": title.strip()[:120], "points": pts})
        widget_sink.append({"id": f"w_{len(widget_sink)}", "kind": "summary",
                            "title": title.strip()[:120], "data": {"tone": t, "points": pts}})
        return "Summary card shown to the patient. Continue your plain-language reply."

    @tool
    async def render_widget(kind: str, title: str, data_json: str) -> str:
        """Render a rich, interactive WIDGET in the chat alongside your written reply — for
        structured or visual information that reads better as a component than as prose.
        Call this IN ADDITION to a short written answer. Reuse [source: Type/id] citations
        inside item text. `data_json` is a JSON object string. Valid kinds:
        - "safety-alert": {"severity":"block|warn|info","items":["High-risk penicillin allergy [source: AllergyIntolerance/1005]"]}
        - "metric-trend": {"label":"Systolic BP","unit":"mmHg","points":[{"t":"2026-01","v":128},{"t":"2026-03","v":134}]}
        - "stat-grid": {"stats":[{"label":"HbA1c","value":"7.2%","tone":"warn"},{"label":"BP","value":"128/82"}]}
        - "record-links": {"items":[{"label":"Metformin 500mg","ref":"MedicationRequest/2"}]}
        - "next-best-action": {"actions":[{"id":"book","label":"Book a follow-up"},{"id":"refill","label":"Refill metformin"}]}
        - "timeline": {"events":[{"t":"2026-01-10","label":"Metformin started","ref":"MedicationRequest/2"}]}
        """
        k = kind.strip()
        if k not in _WIDGET_KINDS:
            return f"Unknown widget kind '{kind}'. Valid: {', '.join(sorted(_WIDGET_KINDS))}."
        try:
            data = json.loads(data_json)
            if not isinstance(data, dict):
                raise ValueError("data must be a JSON object")
        except Exception as exc:  # noqa: BLE001 — narratable, never raise
            return f"Could not render the widget — data_json must be a JSON object ({exc})."
        widget_sink.append({"id": f"w_{len(widget_sink)}", "kind": k, "title": title.strip()[:120], "data": data})
        return f"Rendered a {k} widget in the chat. Now continue your written reply."

    read_tools: list[BaseTool] = [
        get_patient_summary,
        get_record_overview,
        get_conditions,
        get_medications,
        get_allergies,
        get_vitals,
        get_lab_results,
        get_immunizations,
        get_encounters,
        get_clinical_notes,
        get_procedures,
        get_appointments,
        get_family_history,
        get_social_history,
    ]
    # Persona scoping: patients never receive medication-screening or prescription
    # tools; clinicians never receive the patient-facing summary-card tool. Both
    # get render_widget (a display tool — no write side effects).
    if audience == "patient":
        return [*read_tools, present_card, render_widget]
    return [*read_tools, screen_medication, draft_prescription, render_widget]

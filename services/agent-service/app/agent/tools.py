"""Patient-scoped clinical tools that read the FHIR record (04 §2.3).

Every read tool returns human-readable content AND records the FHIR resources it
touched into a shared `sources` list, so the chat layer can surface citation
chips that link back to the source resources (FR-3.4). In S1/S3 dev the tools
hit HAPI directly; in the target design they route through core-api's
decision-checked path so consent/authz apply (04 §1) — same tool surface.
"""

from __future__ import annotations

from typing import Any

import httpx
from langchain_core.tools import BaseTool, tool

# System URI for the PHN identifier (03 §3).
PHN_SYSTEM = "https://fhir.medagent.health.lk/id/phn"


class FhirClient:
    """Thin async FHIR reader scoped to one patient."""

    def __init__(self, base_url: str, patient_fhir_id: str, sources: list[dict[str, Any]]):
        self._base = base_url.rstrip("/")
        self._pid = patient_fhir_id
        self._sources = sources

    async def _search(self, resource_type: str, params: dict[str, str]) -> list[dict[str, Any]]:
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
            self._cite(r)
        return entries

    async def _read(self, resource_type: str, rid: str) -> dict[str, Any] | None:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self._base}/{resource_type}/{rid}",
                headers={"Accept": "application/fhir+json"},
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            r = resp.json()
        self._cite(r)
        return r

    def _cite(self, resource: dict[str, Any]) -> None:
        ref = f"{resource.get('resourceType')}/{resource.get('id')}"
        if not any(s["ref"] == ref for s in self._sources):
            self._sources.append(
                {
                    "ref": ref,
                    "resource_type": resource.get("resourceType"),
                    "id": resource.get("id"),
                }
            )


def _codeable(cc: dict[str, Any] | None) -> str:
    if not cc:
        return "?"
    if cc.get("text"):
        return cc["text"]
    codings = cc.get("coding", [])
    if codings:
        c = codings[0]
        return c.get("display") or f"{c.get('system','')}|{c.get('code','')}"
    return "?"


def build_patient_tools(
    fhir_base_url: str, patient_fhir_id: str, sources: list[dict[str, Any]]
) -> list[BaseTool]:
    """Build the read tools for one patient. `sources` is appended to as tools run."""
    fhir = FhirClient(fhir_base_url, patient_fhir_id, sources)
    pid = patient_fhir_id

    @tool
    async def get_patient_summary() -> str:
        """Personal details: name, date of birth, gender, and identifiers for the current patient."""
        p = await fhir._read("Patient", pid)
        if not p:
            return "Patient not found."
        name = p.get("name", [{}])[0]
        full = " ".join(name.get("given", []) + [name.get("family", "")]).strip()
        phn = next(
            (i["value"] for i in p.get("identifier", []) if i.get("system") == PHN_SYSTEM),
            "n/a",
        )
        return (
            f"Name: {full or 'Unknown'} [source: Patient/{pid}]\n"
            f"PHN: {phn}\nDate of Birth: {p.get('birthDate', 'Not recorded')}\n"
            f"Gender: {p.get('gender', 'Not recorded')}"
        )

    @tool
    async def get_conditions() -> str:
        """Active and past diagnoses / conditions (ICD-10 coded) for the patient."""
        rows = await fhir._search("Condition", {"patient": pid})
        if not rows:
            return "No conditions recorded."
        lines = []
        for c in rows:
            status = _codeable(c.get("clinicalStatus"))
            lines.append(f"- {_codeable(c.get('code'))} (status: {status}) [source: Condition/{c.get('id')}]")
        return "Conditions:\n" + "\n".join(lines)

    @tool
    async def get_medications() -> str:
        """Current and past medication requests (prescriptions) for the patient."""
        rows = await fhir._search("MedicationRequest", {"patient": pid})
        if not rows:
            return "No medications recorded."
        lines = []
        for m in rows:
            dose = ""
            di = m.get("dosageInstruction", [])
            if di and di[0].get("text"):
                dose = f" — {di[0]['text']}"
            lines.append(
                f"- {_codeable(m.get('medicationCodeableConcept'))} "
                f"(status: {m.get('status', '?')}){dose} [source: MedicationRequest/{m.get('id')}]"
            )
        return "Medications:\n" + "\n".join(lines)

    @tool
    async def get_allergies() -> str:
        """Known allergies and intolerances (with criticality) for the patient."""
        rows = await fhir._search("AllergyIntolerance", {"patient": pid})
        if not rows:
            return "No allergies recorded."
        lines = []
        for a in rows:
            crit = a.get("criticality", "unknown")
            react = ""
            r = a.get("reaction", [])
            if r and r[0].get("manifestation"):
                react = f", reaction: {_codeable(r[0]['manifestation'][0])}"
            lines.append(
                f"- {_codeable(a.get('code'))} (criticality: {crit}{react}) "
                f"[source: AllergyIntolerance/{a.get('id')}]"
            )
        return "Allergies:\n" + "\n".join(lines)

    @tool
    async def get_vitals() -> str:
        """Recent vital-sign observations (heart rate, blood pressure, etc.) for the patient."""
        rows = await fhir._search(
            "Observation", {"patient": pid, "category": "vital-signs", "_sort": "-date"}
        )
        if not rows:
            return "No vital signs recorded."
        lines = []
        for o in rows:
            vq = o.get("valueQuantity", {})
            val = f"{vq.get('value', '?')} {vq.get('unit', '')}".strip()
            when = o.get("effectiveDateTime", "")
            lines.append(
                f"- {_codeable(o.get('code'))}: {val} ({when}) [source: Observation/{o.get('id')}]"
            )
        return "Vital signs:\n" + "\n".join(lines)

    return [get_patient_summary, get_conditions, get_medications, get_allergies, get_vitals]

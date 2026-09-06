"""SNOMED CT terminology adapter (FACADE) — LICENCE-GATED.

SNOMED CT requires a SNOMED International member/affiliate licence (held nationally,
via the NMRA/health ministry). Full concept resolution (400k+ concepts) needs
`snomed_enabled=true` + a licensed FHIR **terminology server** (`snomed_base_url`,
e.g. Snowstorm/Ontoserver). WITHOUT the licence this adapter still resolves a SMALL,
CLEARLY-UNVERIFIED offline subset of textbook-stable disorder concepts so the seeded
data + demos get displays/validation with no licence.

Safety: it never INVENTS a code it doesn't know. An unknown code with the server off
returns `status=disabled` ("licence/terminology server required") — never a guessed
display. The offline subset is intentionally tiny and disorder-only (drug/allergy
coding varies by edition and is the riskiest to hardcode); the licensed server is the
authoritative source and the subset is labelled non-authoritative everywhere.

Contract mirrors the FHIR terminology operations the licensed server exposes:
  * lookup(code)   → CodeSystem/$lookup  (system+code → display)
  * search(query)  → ValueSet/$expand    (text → matching concepts)
"""

from __future__ import annotations

from typing import Any

from app.config import Settings
from app.integrations import IntegrationResult, NationalClient, disabled_result, ok_result

SNOMED_SYSTEM = "http://snomed.info/sct"

# Tiny, NON-AUTHORITATIVE offline subset — only widely-documented, edition-stable
# DISORDER concepts (no drug/allergy codes, which vary and are unsafe to guess). The
# licensed terminology server is authoritative; this exists so lookups resolve for the
# seeded conditions and demos without a licence. Verify against the licensed edition
# before any clinical use.
_SUBSET: dict[str, str] = {
    "44054006": "Type 2 diabetes mellitus",
    "73211009": "Diabetes mellitus",
    "38341003": "Hypertensive disorder",
    "195967001": "Asthma",
    "13645005": "Chronic obstructive pulmonary disease",
    "22298006": "Myocardial infarction",
    "230690007": "Cerebrovascular accident",
    "233604007": "Pneumonia",
    "56717001": "Tuberculosis",
    "35489007": "Depressive disorder",
}


class SnomedClient(NationalClient):
    """SNOMED CT terminology facade. Offline subset first; the licensed FHIR
    terminology server (when enabled+configured) resolves anything else."""

    integration = "snomed"

    @classmethod
    def from_settings(cls, settings: Settings) -> "SnomedClient":
        return cls(
            enabled=settings.snomed_enabled,
            base_url=settings.snomed_base_url,
            api_key=settings.snomed_api_key,
        )

    def status(self) -> dict[str, Any]:
        s = super().status()
        s["offline_subset_size"] = len(_SUBSET)
        s["licensed_server"] = self.available  # full SNOMED needs the licensed server
        s["note"] = (
            "SNOMED CT is licence-gated; the licensed FHIR terminology server is used "
            "when enabled, else a small non-authoritative offline subset resolves "
            "common disorder concepts"
        )
        return s

    async def lookup(self, code: str, system: str = SNOMED_SYSTEM) -> IntegrationResult:
        """Resolve a code to its display. Offline subset first, then the licensed server."""
        display = _SUBSET.get(code)
        if display and system == SNOMED_SYSTEM:
            return ok_result(
                self.integration,
                {"system": system, "code": code, "display": display, "source": "offline-subset"},
            )
        if not self.available:
            return disabled_result(
                self.integration,
                "code not in the offline subset — a SNOMED licence + terminology server "
                "is required for full lookup",
            )
        return await self._request(
            "GET", "/CodeSystem/$lookup", params={"system": system, "code": code}
        )

    async def search(self, query: str) -> IntegrationResult:
        """Find concepts by display text. Offline subset first, then $expand on the server."""
        q = (query or "").strip().lower()
        hits = [
            {"system": SNOMED_SYSTEM, "code": c, "display": d}
            for c, d in _SUBSET.items()
            if q and q in d.lower()
        ]
        if hits:
            return ok_result(self.integration, {"results": hits, "source": "offline-subset"})
        if not self.available:
            return disabled_result(
                self.integration,
                "no offline-subset match — a SNOMED licence + terminology server is "
                "required for full search",
            )
        return await self._request(
            "GET",
            "/ValueSet/$expand",
            params={"url": f"{SNOMED_SYSTEM}?fhir_vs", "filter": query, "count": "20"},
        )

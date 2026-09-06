"""NDHX / National EHR adapter (FACADE) — 09-integrations-national.md §2.

A FHIR R4 exchange client for the National Digital Health Exchange. Two representative
capabilities from the spec:

  * `push_document(...)` — share a clinical summary to the exchange as a FHIR
    `DocumentReference` (§2.2: canonical R4, no proprietary extensions; PHN carried as
    a `Patient.identifier`). This is the shape an e-Referral / discharge summary crosses
    the exchange in.
  * `fetch_locator(phn)` — look up a patient's national record locator via an MPI
    `Patient` search on the PHN identifier (§2.1: "FHIR REST + national MPI lookup").

Facade posture: live the moment `ndhx_base_url` points at a real NDHX FHIR endpoint
with a valid key; points at services/national-sim in local/dev. OFF by default.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.config import Settings
from app.fhir.helpers import PHN_SYSTEM
from app.integrations import IntegrationResult, NationalClient

# National record-locator identifier system (interim URI, agreed with HIU per §2.2 /
# 03; additive so it is migration-safe when NDHX publishes the canonical system).
NDHX_LOCATOR_SYSTEM = "https://ndhx.health.gov.lk/id/record-locator"


class NdhxClient(NationalClient):
    integration = "ndhx"

    @classmethod
    def from_settings(cls, settings: Settings) -> "NdhxClient":
        return cls(
            enabled=settings.ndhx_enabled,
            base_url=settings.ndhx_base_url,
            api_key=settings.ndhx_api_key,
        )

    async def push_document(
        self,
        *,
        patient_phn: str,
        summary_text: str,
        type_display: str = "Discharge summary",
        author_display: str | None = None,
    ) -> IntegrationResult:
        """Share a clinical summary to NDHX as a FHIR DocumentReference (§2.2)."""
        doc = _document_reference(
            patient_phn=patient_phn,
            summary_text=summary_text,
            type_display=type_display,
            author_display=author_display,
        )
        return await self._request(
            "POST",
            "/DocumentReference",
            json=doc,
            headers={"Content-Type": "application/fhir+json"},
        )

    async def fetch_locator(self, phn: str) -> IntegrationResult:
        """Fetch a patient's national record locator via an MPI Patient search (§2.1).
        Returns the raw FHIR Bundle from the exchange."""
        return await self._request(
            "GET", "/Patient", params={"identifier": f"{PHN_SYSTEM}|{phn}"}
        )


def _document_reference(
    *,
    patient_phn: str,
    summary_text: str,
    type_display: str,
    author_display: str | None,
) -> dict[str, Any]:
    """A minimal, valid FHIR R4 DocumentReference carrying the PHN as the subject
    identifier and the summary as inline plain-text content. Canonical R4 only — no
    proprietary extensions cross the exchange (§2.2)."""
    now = datetime.now(timezone.utc).isoformat()
    doc: dict[str, Any] = {
        "resourceType": "DocumentReference",
        "status": "current",
        "type": {"text": type_display},
        "subject": {
            "identifier": {"system": PHN_SYSTEM, "value": patient_phn},
            "display": f"PHN {patient_phn}",
        },
        "date": now,
        "content": [
            {
                "attachment": {
                    "contentType": "text/plain",
                    "language": "en",
                    "title": type_display,
                    # data would be base64 in a real exchange; the facade keeps it
                    # human-readable text so the sim round-trip is inspectable.
                    "data": summary_text,
                }
            }
        ],
    }
    if author_display:
        doc["author"] = [{"display": author_display}]
    return doc

"""HHIMS adapter (FACADE) — 09-integrations-national.md §3.

A FHIR facade client for HHIMS (~80 state hospitals). The spec's pattern is
**exchange-first coexistence**: a read-only FHIR facade first (§3.1 phase B1), then
referral interop (B2). The platform NEVER writes into HHIMS tables directly
(ADR I-2) — anything HHIMS must receive goes through its own interface as a
structured resource or a human-readable document.

One representative capability:

  * `send_encounter(...)` — exchange an encounter / discharge summary with a hospital
    HIS as a FHIR `Encounter` (the B2 referral-interop write path, delivered through the
    connector's own interface, not a DB write).

Facade posture: live when `hhims_base_url` points at a real hhims-connector FHIR
facade; points at services/national-sim in local/dev. OFF by default.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.config import Settings
from app.fhir.helpers import PHN_SYSTEM
from app.integrations import IntegrationResult, NationalClient


class HhimsClient(NationalClient):
    integration = "hhims"

    @classmethod
    def from_settings(cls, settings: Settings) -> "HhimsClient":
        return cls(
            enabled=settings.hhims_enabled,
            base_url=settings.hhims_base_url,
            api_key=settings.hhims_api_key,
        )

    async def send_encounter(
        self,
        *,
        patient_phn: str,
        summary_text: str,
        encounter_class: str = "AMB",
        reason_text: str | None = None,
    ) -> IntegrationResult:
        """Exchange an encounter / discharge summary with the hospital HIS as a FHIR
        Encounter (§3.1 B2). Goes through the connector's interface — never a DB write."""
        encounter = _encounter(
            patient_phn=patient_phn,
            summary_text=summary_text,
            encounter_class=encounter_class,
            reason_text=reason_text,
        )
        return await self._request(
            "POST",
            "/Encounter",
            json=encounter,
            headers={"Content-Type": "application/fhir+json"},
        )


def _encounter(
    *,
    patient_phn: str,
    summary_text: str,
    encounter_class: str,
    reason_text: str | None,
) -> dict[str, Any]:
    """Minimal, valid FHIR R4 Encounter carrying the PHN as the subject identifier and
    the summary as a narrative note. Free text is passed as narrative, never coded
    speculatively (§3.2: the facade never fabricates codes)."""
    now = datetime.now(timezone.utc).isoformat()
    enc: dict[str, Any] = {
        "resourceType": "Encounter",
        "status": "finished",
        "class": {
            "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
            "code": encounter_class,
        },
        "subject": {
            "identifier": {"system": PHN_SYSTEM, "value": patient_phn},
            "display": f"PHN {patient_phn}",
        },
        "period": {"end": now},
        "text": {
            "status": "generated",
            "div": f'<div xmlns="http://www.w3.org/1999/xhtml">{summary_text}</div>',
        },
    }
    if reason_text:
        enc["reasonCode"] = [{"text": reason_text}]
    return enc

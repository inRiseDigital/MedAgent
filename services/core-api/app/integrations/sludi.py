"""SLUDI adapter (FACADE) — 09-integrations-national.md §5 (MOSIP-based).

A national digital-identity client for SLUDI's MOSIP ID Authentication (IDA) / eKYC.
Two representative capabilities from the spec:

  * `verify_identity(vid_token, otp=...)` — exchange a SLUDI virtual ID (VID) plus an
    OTP (or, later, a biometric) for a yes/no auth result and a MOSIP
    **partner-specific user token** (+ optional eKYC when the patient authorises it).
    This mirrors the OIDC-style token exchange the §5.1 binding flow describes.
  * `resolve_phn(subject_token)` — resolve a verified identity (the partner token) to
    the platform PHN, so a portal/reception login can bind to the right record.

Identity safety (§5.1, ADR I-7): the platform stores ONLY the partner-specific token
(and the VID transiently for the transaction) — NEVER the UIN. This adapter therefore
never asks for, returns, or logs a UIN; a real SLUDI response's UIN field (if present)
is dropped by the caller. Binding is consented, audited and reversible (§5.1).

Facade posture: live when `sludi_base_url` points at a real MOSIP IDA endpoint with a
registered partner id + key; points at services/national-sim in local/dev. OFF by default.
"""

from __future__ import annotations

from app.config import Settings
from app.integrations import IntegrationResult, NationalClient


class SludiClient(NationalClient):
    integration = "sludi"

    def __init__(self, *, client_id: str = "", **kwargs: object) -> None:
        # MOSIP relying-party / MISP partner id (§5.2). Sent as a body field on each
        # auth call rather than a header, matching MOSIP IDA request envelopes.
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._client_id = client_id or ""

    @classmethod
    def from_settings(cls, settings: Settings) -> "SludiClient":
        return cls(
            enabled=settings.sludi_enabled,
            base_url=settings.sludi_base_url,
            api_key=settings.sludi_api_key,
            client_id=settings.sludi_client_id,
        )

    async def verify_identity(
        self, vid_token: str, *, otp: str | None = None, request_ekyc: bool = False
    ) -> IntegrationResult:
        """MOSIP IDA verify (§5.1): VID/token (+OTP) -> yes/no + partner-specific token
        (+ eKYC if requested and authorised). Returns the raw IDA response; the caller
        persists only the partner token, never the UIN."""
        payload: dict[str, object] = {
            "partnerId": self._client_id,
            "individualIdType": "VID",
            "vidToken": vid_token,
            "consentObtained": True,
            "requestEkyc": request_ekyc,
        }
        if otp is not None:
            payload["otp"] = otp
        return await self._request("POST", "/idauthentication/v1/verify", json=payload)

    async def resolve_phn(self, subject_token: str) -> IntegrationResult:
        """Resolve a verified identity (partner-specific token) to the platform PHN."""
        return await self._request(
            "POST",
            "/idauthentication/v1/phn",
            json={"partnerId": self._client_id, "subjectToken": subject_token},
        )

"""National health-integration adapters (FACADES) — docs/solution/09-integrations-national.md.

These are HONEST facades, not a claim of a live national connection. Each adapter
(`ndhx`, `sludi`, `hhims`) is a real `httpx` client that speaks the documented
exchange contract from the §09 spec:

  * NDHX / National EHR  — FHIR R4 exchange (share a summary DocumentReference,
    fetch a national record locator via MPI Patient search). §2.
  * SLUDI (MOSIP)        — ID Authentication (IDA) / eKYC, OIDC-style token
    exchange: verify a national digital identity, resolve it to a PHN. §5.
  * HHIMS                — hospital-HIS FHIR facade: exchange an encounter /
    discharge summary. §3.

The exact same code points at the LOCAL SIMULATOR today
(services/national-sim, wired by infra/compose/docker-compose.national.yml) and at
the REAL NDHX / SLUDI / HHIMS endpoints the moment a base URL + credentials are
configured in Settings. Nothing here fabricates a national record.

Safety posture (§09 + master-plan invariants):
  * Every integration is feature-flagged OFF by default (see config.py). A disabled
    or unconfigured integration returns `IntegrationResult(status="disabled")` — it
    never raises and never blocks care (spec §5.3 fallback, §6.2 risk table).
  * Timeouts + one retry on transient connection errors; upstream failures are
    caught and returned as `status="error"`, surfaced by the router as a clear
    502/503 — not an internal 500.
  * SLUDI stores only the MOSIP partner-specific token, never the UIN (§5.1, ADR I-7).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

# Connection-level errors that mean "the request never got a response" — safe to
# retry once (mirrors fhir_client._RETRYABLE).
_RETRYABLE = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.ReadError,
    httpx.RemoteProtocolError,
)

# status values an IntegrationResult can carry.
OK = "ok"
DISABLED = "disabled"
ERROR = "error"


@dataclass
class IntegrationResult:
    """Typed outcome of a national-integration call. Never an exception across the
    adapter boundary — the router maps this to an HTTP response."""

    integration: str
    status: str  # OK | DISABLED | ERROR
    data: dict[str, Any] = field(default_factory=dict)
    detail: str | None = None
    status_code: int | None = None  # upstream HTTP status when relevant

    @property
    def ok(self) -> bool:
        return self.status == OK

    @property
    def is_disabled(self) -> bool:
        return self.status == DISABLED

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"integration": self.integration, "status": self.status}
        if self.detail is not None:
            out["detail"] = self.detail
        if self.status_code is not None:
            out["upstream_status"] = self.status_code
        if self.data:
            out["data"] = self.data
        return out


def disabled_result(integration: str, detail: str) -> IntegrationResult:
    return IntegrationResult(integration=integration, status=DISABLED, detail=detail)


def ok_result(integration: str, data: dict[str, Any]) -> IntegrationResult:
    return IntegrationResult(integration=integration, status=OK, data=data)


def error_result(
    integration: str, detail: str, *, status_code: int | None = None
) -> IntegrationResult:
    return IntegrationResult(
        integration=integration, status=ERROR, detail=detail, status_code=status_code
    )


def _safe_json(resp: httpx.Response) -> dict[str, Any]:
    try:
        body = resp.json()
    except ValueError:
        return {"raw": resp.text[:1000]}
    return body if isinstance(body, dict) else {"result": body}


class NationalClient:
    """Base httpx client for a national-integration facade.

    Subclasses set `integration` and expose intent-named methods (e.g.
    `push_document`) that delegate to `_request`. A fresh short-lived AsyncClient is
    used per call: these are low-volume exchange/admin calls, not the hot FHIR read
    path, so the shared-pool machinery in fhir_client is unnecessary here.
    """

    integration: str = "national"

    def __init__(
        self,
        *,
        enabled: bool,
        base_url: str,
        api_key: str = "",
        timeout: float = 10.0,
        default_headers: dict[str, str] | None = None,
    ) -> None:
        self._enabled = bool(enabled)
        self._base_url = (base_url or "").rstrip("/")
        self._api_key = api_key or ""
        self._timeout = timeout
        self._default_headers = default_headers or {}

    @property
    def configured(self) -> bool:
        """A base URL is set (so a call could actually reach something)."""
        return bool(self._base_url)

    @property
    def available(self) -> bool:
        """Enabled AND configured — the only state in which a real call is made."""
        return self._enabled and self.configured

    def status(self) -> dict[str, Any]:
        """Health snapshot for GET /integrations/health (no secrets)."""
        return {
            "enabled": self._enabled,
            "configured": self.configured,
            "available": self.available,
            "base_url": self._base_url or None,
            "authenticated": bool(self._api_key),
        }

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {"Accept": "application/fhir+json, application/json", **self._default_headers}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        if extra:
            headers.update(extra)
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> IntegrationResult:
        """Make one call with a timeout and a single retry on a transient connection
        error. Any failure becomes a typed ERROR/DISABLED result — never an exception."""
        if not self.available:
            reason = (
                "integration disabled (feature flag off)"
                if not self._enabled
                else "integration enabled but no base URL configured"
            )
            return disabled_result(self.integration, reason)

        url = self._base_url + path
        last_exc: Exception | None = None
        for _ in range(2):  # initial try + one retry
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.request(
                        method, url, json=json, params=params, headers=self._headers(headers)
                    )
                resp.raise_for_status()
                return ok_result(self.integration, _safe_json(resp))
            except httpx.HTTPStatusError as exc:  # got a response, but non-2xx
                return error_result(
                    self.integration,
                    f"upstream returned {exc.response.status_code}",
                    status_code=exc.response.status_code,
                )
            except _RETRYABLE as exc:  # no response — retry once
                last_exc = exc
                continue
            except httpx.HTTPError as exc:  # other transport error — do not retry
                return error_result(self.integration, f"request failed: {exc}")
        return error_result(self.integration, f"unreachable after retry: {last_exc}")


__all__ = [
    "IntegrationResult",
    "NationalClient",
    "disabled_result",
    "ok_result",
    "error_result",
    "OK",
    "DISABLED",
    "ERROR",
]

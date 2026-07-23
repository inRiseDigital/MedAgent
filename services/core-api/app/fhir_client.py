"""FHIR client — httpx wrapper over FHIR_BASE_URL (03).

The MPI projects to `Patient` and the commit path writes transactions through
this client. All calls go through the gateway path with a service/forwarded
token so the HAPI interceptors (authz, consent, audit) are always exercised —
never a direct DB path.

Connection pooling (S6): a **single shared** `httpx.AsyncClient` per base URL is
reused across requests, with a bounded pool. Creating a client per request (the
earlier shape) opened an unbounded number of pools under load and reused
keep-alive connections HAPI had already closed → intermittent
`RemoteProtocolError: Server disconnected` surfacing as 500s (found by the
record-load k6 gate at 50 VUs). Idempotent reads retry once on a dropped
connection so a stale-keepalive race self-heals instead of failing the request.
"""

from __future__ import annotations

from types import TracebackType
from typing import Any

import httpx

# One shared client per base URL, reused for the process lifetime. asyncio is
# single-threaded and there is no await between the get and the set below, so
# lazy creation cannot race. Closed on app shutdown via close_shared_clients().
_shared_clients: dict[str, httpx.AsyncClient] = {}

# Bounded pool: requests queue for a connection under burst rather than each
# opening its own. keepalive_expiry is kept short so connections HAPI may have
# closed are not held long enough to be reused stale.
_LIMITS = httpx.Limits(max_connections=100, max_keepalive_connections=20, keepalive_expiry=15.0)

# Errors that mean "the request did not get a response" — safe to retry once for
# idempotent methods (a dropped/stale keep-alive connection).
_RETRYABLE = (httpx.RemoteProtocolError, httpx.ConnectError, httpx.ReadError)


def _get_client(base_url: str, timeout: float) -> httpx.AsyncClient:
    key = base_url.rstrip("/")
    client = _shared_clients.get(key)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(
            base_url=key,
            timeout=timeout,
            limits=_LIMITS,
            headers={"Accept": "application/fhir+json"},
        )
        _shared_clients[key] = client
    return client


async def close_shared_clients() -> None:
    """Close all shared clients (call on app shutdown)."""
    for client in list(_shared_clients.values()):
        await client.aclose()
    _shared_clients.clear()


class FHIRClient:
    """Thin async wrapper for the HAPI FHIR R4 endpoint over a shared pool."""

    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self._client = _get_client(base_url, timeout)

    async def __aenter__(self) -> "FHIRClient":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    async def close(self) -> None:
        # No-op: the underlying client is shared and lives for the process.
        # Kept so callers' `async with` / `finally: close()` stay valid.
        return None

    async def _get(self, path: str, *, params: dict[str, str] | None, token: str | None) -> httpx.Response:
        """GET with a single retry on a dropped connection (idempotent)."""
        last: Exception | None = None
        for attempt in range(2):
            try:
                resp = await self._client.get(path, params=params, headers=_auth_header(token))
                resp.raise_for_status()
                return resp
            except _RETRYABLE as exc:  # stale keep-alive / transient — retry once
                last = exc
                continue
        assert last is not None
        raise last

    async def read(self, resource_type: str, resource_id: str, token: str | None = None) -> dict[str, Any]:
        """GET a single resource."""
        resp = await self._get(f"/{resource_type}/{resource_id}", params=None, token=token)
        return dict(resp.json())

    async def search(
        self, resource_type: str, params: dict[str, str], token: str | None = None
    ) -> list[dict[str, Any]]:
        """GET a search bundle and return its resources."""
        resp = await self._get(f"/{resource_type}", params={**params, "_count": "50"}, token=token)
        bundle = resp.json()
        return [e["resource"] for e in bundle.get("entry", []) if "resource" in e]

    async def everything(
        self, resource_type: str, resource_id: str, token: str | None = None
    ) -> dict[str, Any]:
        """Run the instance-level `$everything` operation and return the raw Bundle
        (FR-5.6 / FR-6.4 data-portability export). Returns the full FHIR JSON as-is."""
        resp = await self._get(
            f"/{resource_type}/{resource_id}/$everything", params={"_count": "500"}, token=token
        )
        return dict(resp.json())

    async def create(
        self, resource_type: str, resource: dict[str, Any], token: str | None = None
    ) -> dict[str, Any]:
        """POST a new resource. Retries once only on RemoteProtocolError — the server
        disconnected without sending a response, so the write was not processed."""
        last: Exception | None = None
        for attempt in range(2):
            try:
                resp = await self._client.post(
                    f"/{resource_type}",
                    json=resource,
                    headers={"Content-Type": "application/fhir+json", **_auth_header(token)},
                )
                resp.raise_for_status()
                return dict(resp.json())
            except httpx.RemoteProtocolError as exc:
                last = exc
                continue
        assert last is not None
        raise last


def _auth_header(token: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}

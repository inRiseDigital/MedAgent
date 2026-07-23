"""FHIR client stub — httpx wrapper over FHIR_BASE_URL (03).

S1: interface only. The MPI projects to `Patient` and the commit path writes
transactions through this client in later sprints. All calls go through the
gateway path with a service/forwarded token so the HAPI interceptors (authz,
consent, audit) are always exercised — never a direct DB path.
"""

from __future__ import annotations

from types import TracebackType
from typing import Any

import httpx


class FHIRClient:
    """Thin async wrapper for the HAPI FHIR R4 endpoint."""

    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            headers={"Accept": "application/fhir+json"},
        )

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
        await self._client.aclose()

    async def read(self, resource_type: str, resource_id: str, token: str | None = None) -> dict[str, Any]:
        """GET a single resource. TODO(S1/S3): retries, error mapping, tracing."""
        resp = await self._client.get(
            f"/{resource_type}/{resource_id}", headers=_auth_header(token)
        )
        resp.raise_for_status()
        return dict(resp.json())

    async def search(
        self, resource_type: str, params: dict[str, str], token: str | None = None
    ) -> list[dict[str, Any]]:
        """GET a search bundle and return its resources."""
        resp = await self._client.get(
            f"/{resource_type}", params={**params, "_count": "50"}, headers=_auth_header(token)
        )
        resp.raise_for_status()
        bundle = resp.json()
        return [e["resource"] for e in bundle.get("entry", []) if "resource" in e]

    async def everything(
        self, resource_type: str, resource_id: str, token: str | None = None
    ) -> dict[str, Any]:
        """Run the instance-level `$everything` operation and return the raw Bundle
        (FR-5.6 / FR-6.4 data-portability export). Returns the full FHIR JSON as-is."""
        resp = await self._client.get(
            f"/{resource_type}/{resource_id}/$everything",
            params={"_count": "500"},
            headers=_auth_header(token),
        )
        resp.raise_for_status()
        return dict(resp.json())

    async def create(
        self, resource_type: str, resource: dict[str, Any], token: str | None = None
    ) -> dict[str, Any]:
        """POST a new resource (e.g. MPI → Patient projection). TODO: wire in S1."""
        resp = await self._client.post(
            f"/{resource_type}",
            json=resource,
            headers={"Content-Type": "application/fhir+json", **_auth_header(token)},
        )
        resp.raise_for_status()
        return dict(resp.json())


def _auth_header(token: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}

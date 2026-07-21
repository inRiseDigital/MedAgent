"""Keycloak JWT authentication dependency (02).

Validates Bearer access tokens against the realm's JWKS (fetched from
KEYCLOAK_ISSUER's OIDC discovery document, cached with a TTL). Realm roles are
extracted from `realm_access.roles`.

S1 skeleton notes:
- AUTH_DISABLED=true short-circuits to a static dev principal — local
  bootstrapping only, never set outside local dev.
- Audience (`aud:notify-service`) enforcement is a TODO for when the realm-as-code
  client scopes land (02 §2); issuer, signature, and expiry ARE verified now.
"""

from __future__ import annotations

import time
from typing import Annotated, Any

import httpx
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel


class Principal(BaseModel):
    """The authenticated caller, as asserted by the verified token."""

    subject: str
    roles: list[str]
    claims: dict[str, Any]

    def has_role(self, role: str) -> bool:
        return role in self.roles


class JWKSCache:
    """Fetches and caches the realm signing keys from the INTERNAL certs endpoint.

    We deliberately do NOT follow the discovery document's `jwks_uri`: Keycloak
    reports its public hostname there, which in-cluster services cannot reach
    (split-horizon, 02). Instead we hit `{realm_base_url}/protocol/openid-connect/
    certs` directly over the internal network. Token `iss` is still validated
    against the public issuer in `require_user`.
    """

    def __init__(self, realm_base_url: str, ttl_seconds: int = 300) -> None:
        self._certs_url = realm_base_url.rstrip("/") + "/protocol/openid-connect/certs"
        self._ttl = ttl_seconds
        self._keys: dict[str, Any] = {}
        self._expires_at: float = 0.0

    async def _refresh(self) -> None:
        async with httpx.AsyncClient(timeout=5.0) as client:
            jwks_resp = await client.get(self._certs_url)
            jwks_resp.raise_for_status()
            jwk_set = jwt.PyJWKSet.from_dict(jwks_resp.json())
        self._keys = {k.key_id: k.key for k in jwk_set.keys if k.key_id}
        self._expires_at = time.monotonic() + self._ttl

    async def get_key(self, kid: str) -> Any:
        if time.monotonic() >= self._expires_at:
            await self._refresh()
        if kid not in self._keys:
            # Key rotation may have happened since the last fetch — refresh once.
            await self._refresh()
        key = self._keys.get(kid)
        if key is None:
            raise KeyError(f"unknown signing key id: {kid}")
        return key


_bearer = HTTPBearer(auto_error=False)

_DEV_PRINCIPAL = Principal(
    subject="local-dev",
    roles=["doctor", "nurse", "receptionist", "admin"],
    claims={"auth_disabled": True},
)


async def require_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal:
    """FastAPI dependency: verified Keycloak principal or 401."""
    settings = request.app.state.settings
    if settings.auth_disabled:
        return _DEV_PRINCIPAL

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = credentials.credentials
    jwks: JWKSCache = request.app.state.jwks
    try:
        header = jwt.get_unverified_header(token)
        key = await jwks.get_key(header["kid"])
        claims = jwt.decode(
            token,
            key=key,
            algorithms=["RS256", "ES256"],
            issuer=settings.keycloak_issuer,
            # TODO(S1/S2): enforce audience `aud:notify-service` once the realm client
            # scopes are applied (02 §2). Until then aud is not validated.
            options={"verify_aud": False},
        )
    except (jwt.PyJWTError, KeyError, httpx.HTTPError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    roles = list(claims.get("realm_access", {}).get("roles", []))
    return Principal(subject=str(claims.get("sub", "")), roles=roles, claims=dict(claims))


def require_roles(*required: str) -> Any:
    """Dependency factory: principal must hold at least one of the given roles."""

    async def _check(principal: Annotated[Principal, Depends(require_user)]) -> Principal:
        if not any(principal.has_role(r) for r in required):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient role")
        return principal

    return Depends(_check)

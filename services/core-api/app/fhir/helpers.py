"""Shared FHIR/router helpers (P3.1).

Canonical versions of the small helpers that were copy-pasted across ~10 routers
(PHN system URI, CodeableConcept text, bearer extraction, PHN→Patient resolution).
Routers import these under their existing local names, so call sites are unchanged
and there is exactly one implementation to maintain and test.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request

from app.fhir_client import FHIRClient

# National PHN identifier system (02 §8).
PHN_SYSTEM = "https://fhir.medagent.health.lk/id/phn"


def cc_text(cc: dict[str, Any] | None) -> str:
    """Human-readable text for a FHIR CodeableConcept (text → first coding → "")."""
    if not cc:
        return ""
    if cc.get("text"):
        return cc["text"]
    for c in cc.get("coding", []):
        return c.get("display") or c.get("code") or ""
    return ""


def bearer(request: Request) -> str | None:
    """The raw JWT from an `Authorization: Bearer <jwt>` header, or None."""
    h = request.headers.get("authorization", "")
    return h[7:] if h.lower().startswith("bearer ") else None


async def resolve_pid(fhir: FHIRClient, phn: str) -> dict[str, Any] | None:
    """Resolve a PHN (all-digit) — or a raw FHIR Patient id — to the Patient
    resource dict. Returns None if not found."""
    if not phn.isdigit():
        try:
            return await fhir.read("Patient", phn)
        except Exception:  # noqa: BLE001 — a bad id is simply "not found"
            return None
    rows = await fhir.search("Patient", {"identifier": f"{PHN_SYSTEM}|{phn}"})
    return rows[0] if rows else None


async def resolve_patient_id(fhir: FHIRClient, ref: str) -> str | None:
    """Resolve a PHN or raw Patient id to just the Patient logical id string."""
    if ref.isdigit():
        rows = await fhir.search("Patient", {"identifier": f"{PHN_SYSTEM}|{ref}"})
        if rows:
            return str(rows[0]["id"])
    try:
        return str((await fhir.read("Patient", ref))["id"])
    except Exception:  # noqa: BLE001
        return None

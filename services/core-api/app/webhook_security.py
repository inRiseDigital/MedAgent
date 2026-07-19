"""HMAC verification for the face-service webhook — EXACTLY per 05 §3.

Contract:
    X-MedAgent-Signature: v1=HMAC-SHA256(secret, timestamp + "." + raw_body)
    X-MedAgent-Timestamp: <unix seconds>, |now − timestamp| ≤ 300 s
    X-MedAgent-Key-Id:    key-rotation id → secret lookup (two active keys
                          during rotation, FACE_WEBHOOK_HMAC_KEYS)

Pure functions — no I/O — so signature behaviour is unit-testable in isolation.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Mapping

SIGNATURE_VERSION = "v1"


class WebhookVerificationError(Exception):
    """Raised when a webhook request fails authentication. Message is safe to log."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def compute_signature(secret: str, timestamp: str, raw_body: bytes) -> str:
    """`v1=` + hex(HMAC-SHA256(secret, timestamp + "." + raw_body))."""
    mac = hmac.new(
        secret.encode("utf-8"),
        timestamp.encode("ascii") + b"." + raw_body,
        hashlib.sha256,
    )
    return f"{SIGNATURE_VERSION}={mac.hexdigest()}"


def verify_webhook(
    *,
    signature: str | None,
    timestamp: str | None,
    key_id: str | None,
    raw_body: bytes,
    keys: Mapping[str, str],
    tolerance_seconds: int = 300,
    now: int | None = None,
) -> None:
    """Validate signature headers; raise WebhookVerificationError on any failure.

    Order matters: cheap structural checks, then freshness, then the
    constant-time signature comparison.
    """
    if not signature:
        raise WebhookVerificationError("missing X-MedAgent-Signature")
    if not timestamp:
        raise WebhookVerificationError("missing X-MedAgent-Timestamp")
    if not key_id:
        raise WebhookVerificationError("missing X-MedAgent-Key-Id")

    secret = keys.get(key_id)
    if secret is None:
        raise WebhookVerificationError("unknown key id")

    try:
        ts = int(timestamp)
    except ValueError as exc:
        raise WebhookVerificationError("malformed timestamp") from exc

    current = int(time.time()) if now is None else now
    if abs(current - ts) > tolerance_seconds:
        raise WebhookVerificationError("stale timestamp")

    expected = compute_signature(secret, timestamp, raw_body)
    if not hmac.compare_digest(expected, signature):
        raise WebhookVerificationError("signature mismatch")

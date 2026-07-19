"""Face-webhook signature tests per 05 §3: valid, bad sig, stale timestamp, replay."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.webhook_security import (
    WebhookVerificationError,
    compute_signature,
    verify_webhook,
)
from tests.conftest import TEST_HMAC_KEYS

KEY_ID = "key-test-1"
SECRET = TEST_HMAC_KEYS[KEY_ID]
WEBHOOK_PATH = "/api/v1/integrations/face/events"


def _event_body(event_id: str | None = None) -> bytes:
    return json.dumps(
        {
            "event_id": event_id or str(uuid.uuid4()),
            "event_type": "match",
            "ext_face_id": "enrol-abc123",
            "confidence": 0.97,
            "liveness": "pass",
            "station_id": "kiosk-01",
            "facility_id": "fac-001",
            "occurred_at": "2026-07-19T08:00:00+05:30",
        }
    ).encode()


def _signed_headers(raw: bytes, *, ts: int | None = None, key_id: str = KEY_ID) -> dict[str, str]:
    timestamp = str(ts if ts is not None else int(time.time()))
    return {
        "X-MedAgent-Signature": compute_signature(SECRET, timestamp, raw),
        "X-MedAgent-Timestamp": timestamp,
        "X-MedAgent-Key-Id": key_id,
        "Content-Type": "application/json",
    }


def _client(app: FastAPI) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


# ---- pure verification function ------------------------------------------------


def test_verify_accepts_valid_signature() -> None:
    raw = _event_body()
    ts = "1750000000"
    verify_webhook(
        signature=compute_signature(SECRET, ts, raw),
        timestamp=ts,
        key_id=KEY_ID,
        raw_body=raw,
        keys=TEST_HMAC_KEYS,
        now=1750000000,
    )  # no exception


def test_verify_rejects_bad_signature() -> None:
    raw = _event_body()
    ts = "1750000000"
    with pytest.raises(WebhookVerificationError, match="signature mismatch"):
        verify_webhook(
            signature="v1=" + "0" * 64,
            timestamp=ts,
            key_id=KEY_ID,
            raw_body=raw,
            keys=TEST_HMAC_KEYS,
            now=1750000000,
        )


def test_verify_rejects_tampered_body() -> None:
    raw = _event_body()
    ts = "1750000000"
    sig = compute_signature(SECRET, ts, raw)
    with pytest.raises(WebhookVerificationError, match="signature mismatch"):
        verify_webhook(
            signature=sig,
            timestamp=ts,
            key_id=KEY_ID,
            raw_body=raw + b" ",
            keys=TEST_HMAC_KEYS,
            now=1750000000,
        )


def test_verify_rejects_stale_timestamp() -> None:
    raw = _event_body()
    ts = "1750000000"
    with pytest.raises(WebhookVerificationError, match="stale timestamp"):
        verify_webhook(
            signature=compute_signature(SECRET, ts, raw),
            timestamp=ts,
            key_id=KEY_ID,
            raw_body=raw,
            keys=TEST_HMAC_KEYS,
            now=1750000000 + 301,  # just past the ±300 s window
        )


def test_verify_rejects_unknown_key_id() -> None:
    raw = _event_body()
    ts = "1750000000"
    with pytest.raises(WebhookVerificationError, match="unknown key id"):
        verify_webhook(
            signature=compute_signature(SECRET, ts, raw),
            timestamp=ts,
            key_id="key-retired-0",
            raw_body=raw,
            keys=TEST_HMAC_KEYS,
            now=1750000000,
        )


# ---- endpoint behaviour ---------------------------------------------------------


async def test_endpoint_accepts_valid_event(app: FastAPI) -> None:
    raw = _event_body()
    async with _client(app) as client:
        resp = await client.post(WEBHOOK_PATH, content=raw, headers=_signed_headers(raw))
    assert resp.status_code == 202
    # FakeSession has no patients, so a valid signature resolves to unknown id.
    assert resp.json() == {"status": "unknown_ext_face_id"}


async def test_endpoint_rejects_bad_signature(app: FastAPI) -> None:
    raw = _event_body()
    headers = _signed_headers(raw)
    headers["X-MedAgent-Signature"] = "v1=" + "f" * 64
    async with _client(app) as client:
        resp = await client.post(WEBHOOK_PATH, content=raw, headers=headers)
    assert resp.status_code == 401


async def test_endpoint_rejects_stale_timestamp(app: FastAPI) -> None:
    raw = _event_body()
    headers = _signed_headers(raw, ts=int(time.time()) - 400)
    async with _client(app) as client:
        resp = await client.post(WEBHOOK_PATH, content=raw, headers=headers)
    assert resp.status_code == 401


async def test_endpoint_replay_is_idempotent(app: FastAPI, fake_redis: Any) -> None:
    event_id = str(uuid.uuid4())
    raw = _event_body(event_id)
    async with _client(app) as client:
        first = await client.post(WEBHOOK_PATH, content=raw, headers=_signed_headers(raw))
        second = await client.post(WEBHOOK_PATH, content=raw, headers=_signed_headers(raw))
    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json() == {"status": "duplicate"}
    assert f"face:event:{event_id}" in fake_redis.store

#!/usr/bin/env python3
"""face-sim — Phase A dev stub for the external face-recognition service.

Emits HMAC-signed FaceCheckinEvent webhooks to the gateway on demand so the
check-in flow (webhook -> core-api -> Redis -> notify-service -> SSE) is
testable without the real service. Contract: 05-face-recognition-integration.md §3.

    POST {gateway}/integrations/face/events
    X-MedAgent-Signature: v1=HMAC-SHA256(secret, timestamp + "." + raw_body)
    X-MedAgent-Timestamp: <unix seconds>
    X-MedAgent-Key-Id:    <key rotation id>

Usage (inside the compose network, or from the host against https://localhost):

    python sim.py send                                # one valid match event
    python sim.py send --ext-face-id demo-face-0001 --confidence 0.97
    python sim.py send --count 30                     # burst (clinic opening rush)
    python sim.py send --replay                       # fixed event_id + stale timestamp
    python sim.py send --bad-signature                # garbage HMAC -> must be rejected
    python sim.py send --event-type liveness_fail
    python sim.py idle                                # container default: sleep forever

Stdlib only — runs unmodified on python:3.12-slim, no installs.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
import uuid

DEFAULT_GATEWAY = os.environ.get("GATEWAY_URL", "https://localhost")
DEFAULT_KEY_ID = os.environ.get("FACE_WEBHOOK_HMAC_KEY_ID", "dev-key-1")
DEFAULT_SECRET = os.environ.get("FACE_WEBHOOK_HMAC_SECRET", "dev-face-webhook-secret")
WEBHOOK_PATH = "/integrations/face/events"

# Fixed values for --replay: same event_id every run so idempotency handling
# (duplicate event_id within 24 h -> 202, no effect) and timestamp-freshness
# rejection (|now - ts| > 300 s) can both be exercised.
REPLAY_EVENT_ID = "00000000-0000-4000-8000-00000000f00d"
REPLAY_SKEW_SECONDS = 600  # deliberately outside the 300 s window


def sign(secret: str, timestamp: str, raw_body: bytes) -> str:
    """v1=HMAC-SHA256(secret, timestamp + '.' + raw_body) — 05 §3."""
    mac = hmac.new(
        secret.encode("utf-8"),
        timestamp.encode("utf-8") + b"." + raw_body,
        hashlib.sha256,
    )
    return f"v1={mac.hexdigest()}"


def build_event(args: argparse.Namespace) -> dict:
    now = time.time()
    return {
        "event_id": REPLAY_EVENT_ID if args.replay else str(uuid.uuid4()),
        "event_type": args.event_type,
        "ext_face_id": args.ext_face_id if args.event_type == "match" else None,
        "confidence": args.confidence,
        "liveness": args.liveness,
        "station_id": args.station_id,
        "facility_id": args.facility_id,
        # 'ts' in the S1 shorthand == 'occurred_at' in the binding 05 §3 contract
        "occurred_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(now)),
    }


def post_event(args: argparse.Namespace) -> int:
    raw_body = json.dumps(build_event(args), separators=(",", ":")).encode("utf-8")

    ts = int(time.time())
    if args.replay:
        ts -= REPLAY_SKEW_SECONDS
    timestamp = str(ts)

    signature = sign(args.secret, timestamp, raw_body)
    if args.bad_signature:
        signature = "v1=" + "0" * 64  # syntactically valid, cryptographically wrong

    url = args.gateway.rstrip("/") + WEBHOOK_PATH
    req = urllib.request.Request(
        url,
        data=raw_body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-MedAgent-Signature": signature,
            "X-MedAgent-Timestamp": timestamp,
            "X-MedAgent-Key-Id": args.key_id,
        },
    )

    ctx = ssl.create_default_context()
    if os.environ.get("FACE_SIM_INSECURE_TLS") == "1" or args.insecure:
        # dev only: mkcert CA is not in the container trust store
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
            print(f"-> {resp.status} {resp.reason}  event sent to {url}")
            return 0 if resp.status == 202 else 1
    except urllib.error.HTTPError as exc:
        # Expected outcomes for the negative-path flags:
        #   --bad-signature / --replay(stale ts) -> 401/403
        print(f"-> {exc.code} {exc.reason}  ({url})")
        expected_reject = args.bad_signature or args.replay
        return 0 if (expected_reject and exc.code in (401, 403)) else 1
    except urllib.error.URLError as exc:
        print(f"error: cannot reach gateway at {url}: {exc.reason}", file=sys.stderr)
        return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="face-sim", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("idle", help="sleep forever (container default command)")

    send = sub.add_parser("send", help="POST signed FaceCheckinEvent webhook(s)")
    send.add_argument("--gateway", default=DEFAULT_GATEWAY)
    send.add_argument("--key-id", default=DEFAULT_KEY_ID)
    send.add_argument("--secret", default=DEFAULT_SECRET)
    send.add_argument("--ext-face-id", default="demo-face-0001",
                      help="opaque enrolment id (seed marks ~10 demo patients)")
    send.add_argument("--confidence", type=float, default=0.96)
    send.add_argument("--event-type", default="match",
                      choices=["match", "no_match", "liveness_fail"])
    send.add_argument("--liveness", default="pass",
                      choices=["pass", "fail", "not_performed"])
    send.add_argument("--station-id", default="kiosk-01")
    send.add_argument("--facility-id", default="facility-pilot")
    send.add_argument("--count", type=int, default=1, help="events to send")
    send.add_argument("--interval", type=float, default=0.0,
                      help="seconds between events when --count > 1")
    send.add_argument("--replay", action="store_true",
                      help="fixed event_id + stale timestamp (expects 401/403 or idempotent 202)")
    send.add_argument("--bad-signature", action="store_true",
                      help="send a wrong HMAC (expects 401/403)")
    send.add_argument("--insecure", action="store_true",
                      help="skip TLS verification (dev/mkcert)")

    args = parser.parse_args(argv)

    if args.command == "idle":
        print("face-sim idle — trigger with: docker compose exec face-sim "
              "python /opt/face-sim/sim.py send [flags]")
        while True:
            time.sleep(3600)

    rc = 0
    for i in range(args.count):
        rc = max(rc, post_event(args))
        if args.interval and i < args.count - 1:
            time.sleep(args.interval)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())

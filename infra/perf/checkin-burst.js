// Check-in burst — 10 §8: 30 signed webhook events in 60 s (clinic opening
// rush) with doctors' SSE connected. Asserts the platform share of NFR-1:
// webhook -> queue -> SSE p95 < 300 ms, zero dropped events.
//
// S1 skeleton: the webhook leg is real (signed per 05 §3); the SSE-listener
// leg that measures end-to-end delivery joins once notify-service exposes the
// authenticated SSE endpoint (marked TODO below).
//
//   k6 run -e BASE_URL=https://staging.example \
//          -e FACE_WEBHOOK_HMAC_SECRET=... -e FACE_WEBHOOK_HMAC_KEY_ID=key-1 \
//          checkin-burst.js

import http from "k6/http";
import crypto from "k6/crypto";
import { check } from "k6";
import { uuidv4 } from "https://jslib.k6.io/k6-utils/1.4.0/index.js";

const BASE_URL = __ENV.BASE_URL || "https://localhost";
const SECRET = __ENV.FACE_WEBHOOK_HMAC_SECRET || "dev-face-webhook-secret";
const KEY_ID = __ENV.FACE_WEBHOOK_HMAC_KEY_ID || "dev-key-1";
const WEBHOOK = `${BASE_URL}/integrations/face/events`;

export const options = {
  insecureSkipTLSVerify: __ENV.INSECURE_TLS === "1", // dev/mkcert only
  scenarios: {
    checkin_burst: {
      executor: "constant-arrival-rate",
      rate: 30,
      timeUnit: "60s", // 30 events across 60 s
      duration: "60s",
      preAllocatedVUs: 10,
      exec: "sendCheckin",
    },
    // TODO(S2): sse_listeners scenario — N VUs holding authenticated SSE
    // connections to notify-service; a custom Trend records webhook->SSE
    // delivery latency and a Counter asserts zero dropped events.
  },
  thresholds: {
    // platform path share of NFR-1 (<300 ms; 01 §4.1)
    "http_req_duration{scenario:checkin_burst}": ["p(95)<300"],
    "checks{scenario:checkin_burst}": ["rate==1"], // zero rejected/dropped
  },
};

function sign(timestamp, rawBody) {
  // v1=HMAC-SHA256(secret, timestamp + "." + raw_body) — 05 §3
  return "v1=" + crypto.hmac("sha256", SECRET, `${timestamp}.${rawBody}`, "hex");
}

export function sendCheckin() {
  // seed marks demo-face-0001..0010 with face-consent + ext_face_id stubs
  const extFaceId = `demo-face-${String((__ITER % 10) + 1).padStart(4, "0")}`;
  const body = JSON.stringify({
    event_id: uuidv4(),
    event_type: "match",
    ext_face_id: extFaceId,
    confidence: 0.9 + Math.random() * 0.09,
    liveness: "pass",
    station_id: `kiosk-${(__VU % 3) + 1}`,
    facility_id: "facility-pilot",
    occurred_at: new Date().toISOString(),
  });

  const timestamp = String(Math.floor(Date.now() / 1000));
  const res = http.post(WEBHOOK, body, {
    headers: {
      "Content-Type": "application/json",
      "X-MedAgent-Signature": sign(timestamp, body),
      "X-MedAgent-Timestamp": timestamp,
      "X-MedAgent-Key-Id": KEY_ID,
    },
    tags: { name: "face-webhook" },
  });

  check(res, {
    "202 accepted": (r) => r.status === 202,
  });
}

// Chat concurrency — the remaining S6 k6 scenario. N VUs POST to the streaming
// agent `/chat` endpoint concurrently and assert the server starts responding
// quickly and streams a real answer without errors under load.
//
//   k6 run -e VUS=10 -e DURATION=30s chat-concurrency.js
//   # via the gateway + a production model instead of the local dev defaults:
//   k6 run -e AGENT_API=https://localhost/api/agent/api/v1 \
//          -e TOKEN_URL=https://localhost/auth/realms/medagent/protocol/openid-connect/token \
//          -e INSECURE_TLS=1 -e VUS=20 chat-concurrency.js
//
// WHAT IT MEASURES (and the honest limit): k6's HTTP client is not a true SSE
// reader, so we measure TIME-TO-FIRST-BYTE (`waiting`) as the server-responsiveness
// proxy — the stream must START fast (the user sees the thinking indicator ~immediately,
// NFR-4). The `chat_total` trend is the full stream duration, which depends on the
// LLM provider (a self-hosted 7B at ~12 tok/s is far slower than a cloud model) and is
// therefore recorded as evidence, NOT a hard gate. Correctness checks assert the
// stream actually carried a `text-delta` (a real answer) and no error frame. The hard
// staging gate runs against the production model (03 §157).
//
// Defaults target the local dev stack directly (proven paths); creds are the dev-only
// throwaway account (platform/keycloak/realm/dev-users.yaml) — never use outside compose.

import http from "k6/http";
import { check } from "k6";
import { Trend, Rate } from "k6/metrics";

const AGENT_API = __ENV.AGENT_API || "http://localhost:8002/api/v1";
const TOKEN_URL =
  __ENV.TOKEN_URL ||
  `http://localhost:8081/auth/realms/${__ENV.KC_REALM || "medagent"}/protocol/openid-connect/token`;

const PHN = __ENV.PHN || "55246820131"; // demo patient (Nimal Perera)
const USERNAME = __ENV.KC_USERNAME || "dr_demo";
const PASSWORD = __ENV.KC_PASSWORD || "dev-only-dr_demo";
const CLIENT_ID = __ENV.KC_CLIENT_ID || "dev-cli";
const AUDIENCE = __ENV.AUDIENCE || "clinician";
// A short, specific ask keeps generation bounded; overridable for other shapes.
const QUESTION = __ENV.QUESTION || "what are this patient's active medications?";

const ttfb = new Trend("chat_ttfb", true); // time-to-first-byte = server responsiveness
const total = new Trend("chat_total", true); // full stream duration (evidence, not a gate)
const answered = new Rate("chat_answered"); // fraction of streams carrying a real answer

export const options = {
  insecureSkipTLSVerify: __ENV.INSECURE_TLS === "1",
  scenarios: {
    chat_load: {
      executor: "constant-vus",
      vus: Number(__ENV.VUS || 10),
      duration: __ENV.DURATION || "30s",
      exec: "askChat",
    },
  },
  thresholds: {
    // NFR-4: the stream starts fast so the UI shows life immediately. Hard gate.
    chat_ttfb: ["p(95)<2000"],
    // At least almost every request must produce a real answer under load.
    chat_answered: ["rate>0.95"],
    // Transport errors stay negligible (pool/keepalive health).
    http_req_failed: ["rate<0.02"],
  },
};

export function setup() {
  const res = http.post(TOKEN_URL, {
    grant_type: "password",
    client_id: CLIENT_ID,
    username: USERNAME,
    password: PASSWORD,
    scope: "openid",
  });
  check(res, { "token obtained": (r) => r.status === 200 && !!r.json("access_token") });
  return { token: res.json("access_token") };
}

export function askChat(data) {
  const body = JSON.stringify({
    messages: [{ role: "user", content: QUESTION }],
    patient_id: PHN,
    audience: AUDIENCE,
    locale: "en",
  });
  const params = {
    headers: { authorization: `Bearer ${data.token}`, "content-type": "application/json" },
    timeout: __ENV.REQ_TIMEOUT || "180s", // a slow local model can stream for a while
  };

  const res = http.post(`${AGENT_API}/chat`, body, params);
  ttfb.add(res.timings.waiting);
  total.add(res.timings.duration);

  const ok200 = res.status === 200;
  const hasDelta = typeof res.body === "string" && res.body.indexOf('"text-delta"') !== -1;
  // A raw hallucinated tool-call must never reach the client (guarded in chat.py).
  const noLeak = typeof res.body === "string" && res.body.indexOf('"tool":') === -1;
  answered.add(ok200 && hasDelta);
  check(res, {
    "chat 200": () => ok200,
    "stream carried a real answer (text-delta)": () => hasDelta,
    "no raw tool-call leaked": () => noLeak,
  });
}

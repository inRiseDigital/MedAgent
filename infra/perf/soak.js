// Soak — the remaining S6 k6 scenario. A low, steady request rate over a long
// window to surface SLOW problems that a burst test misses: memory leaks,
// connection-pool exhaustion, keepalive rot, latency drift, gradual error creep.
//
//   k6 run -e DURATION=30m soak.js
//   # heavier / via gateway:
//   k6 run -e RPS=5 -e DURATION=1h -e API=https://localhost/api/core/api/v1 \
//          -e TOKEN_URL=https://localhost/auth/realms/medagent/protocol/openid-connect/token \
//          -e INSECURE_TLS=1 soak.js
//
// It mixes the two cheapest real reads (patient summary + demographic search) at a
// modest arrival rate. The gate is STABILITY, not speed: error rate stays ~0 and p95
// does not drift upward across the soak. Defaults target the local dev stack (proven
// paths); a Linux/staging runner avoids the Windows client-side ephemeral-port noise
// documented in record-load.js. Creds are the dev-only throwaway account.

import http from "k6/http";
import { check } from "k6";
import { Trend, Rate } from "k6/metrics";

const API = __ENV.API || "http://localhost:8001/api/v1";
const TOKEN_URL =
  __ENV.TOKEN_URL ||
  `http://localhost:8081/auth/realms/${__ENV.KC_REALM || "medagent"}/protocol/openid-connect/token`;

const PHN = __ENV.PHN || "55246820131";
const USERNAME = __ENV.KC_USERNAME || "dr_demo";
const PASSWORD = __ENV.KC_PASSWORD || "dev-only-dr_demo";
const CLIENT_ID = __ENV.KC_CLIENT_ID || "dev-cli";

const readTrend = new Trend("soak_read_duration", true);
const errRate = new Rate("soak_errors");

export const options = {
  insecureSkipTLSVerify: __ENV.INSECURE_TLS === "1",
  scenarios: {
    soak: {
      executor: "constant-arrival-rate",
      rate: Number(__ENV.RPS || 3), // requests per second
      timeUnit: "1s",
      duration: __ENV.DURATION || "30m",
      preAllocatedVUs: Number(__ENV.VUS || 10),
      maxVUs: Number(__ENV.MAX_VUS || 30),
      exec: "steadyRead",
    },
  },
  thresholds: {
    // Stability gate: errors negligible over the whole soak.
    soak_errors: ["rate<0.01"],
    http_req_failed: ["rate<0.01"],
    // Latency must stay bounded (no creep). Generous ceiling — the signal is a FLAT
    // trend over time; a rising p95 shows in the time-series even under this bar.
    soak_read_duration: ["p(95)<2500"],
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

export function steadyRead(data) {
  const params = { headers: { authorization: `Bearer ${data.token}` } };
  // Alternate summary / search so both the FHIR read path and the MPI search path
  // are exercised continuously.
  const useSearch = __ITER % 2 === 1;
  const res = useSearch
    ? http.get(`${API}/patients?name=Perera`, params)
    : http.get(`${API}/patients/${PHN}/summary`, params);
  readTrend.add(res.timings.duration);
  const ok = res.status === 200;
  errRate.add(!ok);
  check(res, { "read 200": () => ok });
}

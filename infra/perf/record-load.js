// Record load — 10 §8 / README: N VUs opening patient summaries through the
// real platform path (gateway -> core-api -> HAPI FHIR). Asserts NFR-2: full
// summary p95 < 2 s, and that the HAPI connection pool does not exhaust under
// sustained concurrency (error rate ~0). A second check tracks the demographic
// search endpoint against the tighter canonical-set target (03 §6.2 / §157:
// p95 < 500 ms at staging load — asserted softly here since single-node dev
// docker is not staging-representative).
//
//   k6 run -e BASE_URL=https://localhost -e INSECURE_TLS=1 \
//          -e VUS=50 -e DURATION=30s record-load.js
//
// NOTE (local dev on Windows): long high-VU runs accumulate false
// http_req_failed from the k6 *client* exhausting ephemeral ports / TIME_WAIT
// sockets — the requests never reach the server (core-api logs stay clean). A
// short run (~15 s) or a Linux CI runner avoids it. The real NFR gate runs on
// staging (03 §157). This is a load *harness*, not the staging gate.
//
// Secrets (staff creds) come from the environment; the defaults below are the
// dev-only throwaway account (platform/keycloak/realm/dev-users.yaml) and must
// never be used outside the local compose stack.

import http from "k6/http";
import { check } from "k6";
import { Trend } from "k6/metrics";

const BASE_URL = __ENV.BASE_URL || "https://localhost";
// core-api sits behind the gateway at /api/core/* (prefix stripped -> service
// serves /api/v1/*). See platform/gateway/dynamic/routes.yaml. API_BASE and
// TOKEN_URL can be overridden to target core-api / Keycloak directly (bypassing
// the gateway + self-signed TLS) when isolating edge vs backend latency in dev.
const API = __ENV.API_BASE || `${BASE_URL}/api/core/api/v1`;
const TOKEN_URL =
  __ENV.TOKEN_URL ||
  `${BASE_URL}/auth/realms/${__ENV.KC_REALM || "medagent"}/protocol/openid-connect/token`;

const PHN = __ENV.PHN || "55246820131"; // demo patient (Nimal Perera)
const USERNAME = __ENV.KC_USERNAME || "dr_demo";
const PASSWORD = __ENV.KC_PASSWORD || "dev-only-dr_demo";
const CLIENT_ID = __ENV.KC_CLIENT_ID || "dev-cli";

const summaryTrend = new Trend("summary_duration", true);
const searchTrend = new Trend("search_duration", true);

export const options = {
  insecureSkipTLSVerify: __ENV.INSECURE_TLS === "1", // dev/self-signed only
  scenarios: {
    record_load: {
      executor: "constant-vus",
      vus: Number(__ENV.VUS || 50),
      duration: __ENV.DURATION || "30s",
      exec: "openSummary",
    },
  },
  thresholds: {
    // NFR-2: full patient summary p95 < 2 s (06 §95, 03 §157). Hard gate.
    "summary_duration": ["p(95)<2000"],
    // HAPI pool no exhaustion: request errors stay negligible under load.
    "http_req_failed": ["rate<0.01"],
    // Canonical search-set target (03 §6.2): p95 < 500 ms at staging load.
    // Soft here (dev docker != staging) — recorded as evidence, breach warns.
    "search_duration": ["p(95)<1500"],
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

export function openSummary(data) {
  const params = { headers: { authorization: `Bearer ${data.token}` } };

  const summary = http.get(`${API}/patients/${PHN}/summary`, params);
  summaryTrend.add(summary.timings.duration);
  check(summary, {
    "summary 200": (r) => r.status === 200,
    "summary has patient": (r) => !!r.json("patient.name"),
  });

  // Exercise the demographic search on the same VU (canonical read set).
  const search = http.get(`${API}/patients?name=Perera`, params);
  searchTrend.add(search.timings.duration);
  check(search, { "search 200": (r) => r.status === 200 });
}

#!/usr/bin/env python3
"""national-sim — local simulator for Sri Lanka's national health systems.

Implements the three national endpoints the core-api adapters call
(app/integrations/{ndhx,sludi,hhims}.py), returning plausible canned FHIR/JSON so the
facades are exercisable END-TO-END without a real national system. This is a
SIMULATOR (a stand-in), not a real national service — the whole point is that the same
adapter code runs unchanged against it and against the real NDHX/SLUDI/HHIMS endpoints.

Contract source: docs/solution/09-integrations-national.md (§2 NDHX, §3 HHIMS, §5 SLUDI).

Endpoints (base paths match docker-compose.national.yml *_BASE_URL):
    NDHX  (§2)
      POST /ndhx/DocumentReference        -> 201, echo + assigned id (share a summary)
      GET  /ndhx/Patient?identifier=sys|phn -> 200, FHIR searchset Bundle carrying a
                                              national record locator identifier
    SLUDI (§5, MOSIP IDA)
      POST /sludi/idauthentication/v1/verify -> 200, {authStatus, partnerSpecificUserToken,
                                                 eKYC?}  (NEVER returns a UIN — §5.1/ADR I-7)
      POST /sludi/idauthentication/v1/phn    -> 200, {phn, subjectToken}
    HHIMS (§3)
      POST /hhims/Encounter               -> 201, ack echo + assigned id
    Simulator self
      GET  /healthz                       -> 200, {"status": "ok"}

Stdlib only — runs unmodified on python:3.12-slim with NO installs (same discipline as
infra/compose/face-sim). `import sim` has no side effects; `python sim.py` serves.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

# Identifier systems mirrored from the adapters (app/fhir/helpers.py, integrations/ndhx.py).
PHN_SYSTEM = "https://fhir.medagent.health.lk/id/phn"
NDHX_LOCATOR_SYSTEM = "https://ndhx.health.gov.lk/id/record-locator"

LISTEN_HOST = os.environ.get("NATIONAL_SIM_HOST", "0.0.0.0")
LISTEN_PORT = int(os.environ.get("NATIONAL_SIM_PORT", "8000"))


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())


def _digest(*parts: str) -> str:
    """Deterministic short hex id from inputs — stable canned values per input."""
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------- NDHX


def ndhx_document_reference(body: dict) -> tuple[int, dict]:
    """Accept a shared DocumentReference; echo it back with an assigned id + a national
    master locator (what a real NDHX node returns on ingest)."""
    phn = _subject_phn(body) or "unknown"
    doc = dict(body)
    doc.setdefault("resourceType", "DocumentReference")
    doc["id"] = "ndhx-doc-" + _digest(phn, _now())
    doc["status"] = doc.get("status", "current")
    doc["masterIdentifier"] = {
        "system": NDHX_LOCATOR_SYSTEM,
        "value": "NDHX-" + _digest("locator", phn),
    }
    doc["meta"] = {"versionId": "1", "lastUpdated": _now(), "source": "national-sim/ndhx"}
    return 201, doc


def ndhx_patient_search(query: dict[str, list[str]]) -> tuple[int, dict]:
    """Return a FHIR searchset Bundle for an MPI Patient lookup by PHN identifier,
    carrying the national record locator (§2.1)."""
    identifier = (query.get("identifier") or [""])[0]
    phn = identifier.split("|", 1)[1] if "|" in identifier else identifier
    locator = "NDHX-" + _digest("locator", phn or "unknown")
    patient = {
        "resourceType": "Patient",
        "id": "ndhx-pat-" + _digest(phn or "unknown"),
        "identifier": [
            {"system": PHN_SYSTEM, "value": phn},
            {"system": NDHX_LOCATOR_SYSTEM, "value": locator},
        ],
        "active": True,
    }
    bundle = {
        "resourceType": "Bundle",
        "type": "searchset",
        "total": 1 if phn else 0,
        "meta": {"source": "national-sim/ndhx"},
        "entry": ([{"resource": patient}] if phn else []),
    }
    return 200, bundle


# --------------------------------------------------------------------------- SLUDI


def sludi_verify(body: dict) -> tuple[int, dict]:
    """MOSIP IDA verify. Canned success: yes + a partner-specific user token, and eKYC
    when requested. Deliberately returns NO UIN — the platform never receives one
    (§5.1, ADR I-7)."""
    vid = str(body.get("vidToken", ""))
    partner = str(body.get("partnerId", "sim-partner"))
    otp_ok = "otp" not in body or bool(body.get("otp"))
    if not vid or not otp_ok:
        return 200, {"authStatus": False, "errors": [{"errorCode": "IDA-MLC-002",
                     "errorMessage": "authentication failed (missing VID/OTP)"}]}
    resp = {
        "authStatus": True,
        "authToken": _digest("auth", vid),
        # MOSIP partner-specific user token — the ONLY identity token we persist.
        "partnerSpecificUserToken": _digest("psut", partner, vid),
        "responseTime": _now(),
    }
    if body.get("requestEkyc"):
        resp["eKYC"] = {
            "name": "Sim Citizen",
            "dateOfBirth": "1990-01-01",
            "gender": "Male",
            "address": "Colombo, Sri Lanka",
        }
    return 200, resp


def sludi_phn(body: dict) -> tuple[int, dict]:
    """Resolve a verified identity (partner-specific token) to a platform PHN."""
    token = str(body.get("subjectToken", ""))
    if not token:
        return 200, {"resolved": False, "detail": "no subjectToken"}
    # Deterministic 12-digit PHN from the token (canned).
    phn = str(int(_digest("phn", token), 16))[:12].rjust(12, "0")
    return 200, {"resolved": True, "phn": phn, "subjectToken": token}


# --------------------------------------------------------------------------- HHIMS


def hhims_encounter(body: dict) -> tuple[int, dict]:
    """Accept an encounter/discharge summary; ack with an assigned HHIMS id."""
    phn = _subject_phn(body) or "unknown"
    enc = dict(body)
    enc.setdefault("resourceType", "Encounter")
    enc["id"] = "hhims-enc-" + _digest(phn, _now())
    enc["status"] = enc.get("status", "finished")
    enc["meta"] = {"versionId": "1", "lastUpdated": _now(), "source": "national-sim/hhims"}
    return 201, enc


# --------------------------------------------------------------------------- helpers


def _subject_phn(resource: dict) -> str | None:
    subject = resource.get("subject") or {}
    identifier = subject.get("identifier") or {}
    return identifier.get("value")


# --------------------------------------------------------------------------- server


class Handler(BaseHTTPRequestHandler):
    server_version = "national-sim/1.0"

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/fhir+json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if not length:
            return {}
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}
        return data if isinstance(data, dict) else {"_body": data}

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        parsed = urlparse(self.path)
        path, query = parsed.path, parse_qs(parsed.query)
        if path == "/healthz":
            return self._send(200, {"status": "ok", "service": "national-sim"})
        if path == "/ndhx/Patient":
            return self._send(*ndhx_patient_search(query))
        return self._send(404, {"error": "not found", "path": path})

    def do_POST(self) -> None:  # noqa: N802 (http.server API)
        path = urlparse(self.path).path
        body = self._read_json()
        if path == "/ndhx/DocumentReference":
            return self._send(*ndhx_document_reference(body))
        if path == "/sludi/idauthentication/v1/verify":
            return self._send(*sludi_verify(body))
        if path == "/sludi/idauthentication/v1/phn":
            return self._send(*sludi_phn(body))
        if path == "/hhims/Encounter":
            return self._send(*hhims_encounter(body))
        return self._send(404, {"error": "not found", "path": path})

    def log_message(self, fmt: str, *args: object) -> None:
        # Compact single-line access log to stdout (compose captures it).
        print("national-sim %s - %s" % (self.address_string(), fmt % args), flush=True)


def serve() -> None:
    server = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), Handler)
    print(f"national-sim listening on {LISTEN_HOST}:{LISTEN_PORT} "
          f"(NDHX §2 / SLUDI §5 / HHIMS §3 facades)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    serve()

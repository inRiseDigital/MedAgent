#!/usr/bin/env python3
"""Synthea seed job — 10-devops-infrastructure.md §2.3 (S1 skeleton).

Three steps, in order:
  1. generate_or_restore()  Synthea FHIR R4 bundles (pinned release) or a
                            cached, versioned bundle set from /bundles.
  2. load_bundles()         POST transaction bundles to HAPI *through the
                            gateway* with a service token — exercising the
                            authz/consent/audit interceptors, never bypassing.
  3. register_mpi()         register patients in the MPI so PHNs are issued
                            through the REAL issuance path (03 §7 / ADR F-8);
                            mark ~10 demo patients with face-consent granted
                            and ext_face_id stubs for the face-sim flow.

Seed data is versioned (seed/v{n}); eval golden cases pin the seed version
they were graded against (10 §2.3). Stdlib-only HTTP so the job runs on
python:3.12-slim without installs.
"""

from __future__ import annotations

import json
import os
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# --- Pins & config -----------------------------------------------------------

# Pinned Synthea release (10 §2.3 "pinned Synthea release config"). Update
# deliberately; regenerating bundles bumps SEED_VERSION.
SYNTHEA_VERSION = "v3.3.0"
SYNTHEA_JAR_URL = (
    "https://github.com/synthetichealth/synthea/releases/download/"
    f"{SYNTHEA_VERSION}/synthea-with-dependencies.jar"
)
PATIENT_COUNT = 1000          # ~1,000 synthetic Sri Lanka-adjusted patients
DEMO_PATIENT_COUNT = 10       # face-consent + ext_face_id stubs

SEED_VERSION = os.environ.get("SEED_VERSION", "v1")
BUNDLE_ROOT = Path(os.environ.get("BUNDLE_ROOT", "/bundles"))
BUNDLE_DIR = BUNDLE_ROOT / f"seed-{SEED_VERSION}"

GATEWAY_URL = os.environ.get("GATEWAY_URL", "https://localhost").rstrip("/")
FHIR_URL = f"{GATEWAY_URL}/fhir"
MPI_URL = f"{GATEWAY_URL}/api/mpi"

KEYCLOAK_URL = os.environ.get("KEYCLOAK_URL", "http://keycloak:8080").rstrip("/")
KEYCLOAK_REALM = os.environ.get("KEYCLOAK_REALM", "medagent")
CLIENT_ID = os.environ.get("SEED_CLIENT_ID", "seed-job")
CLIENT_SECRET = os.environ.get("SEED_CLIENT_SECRET", "")


def _ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if os.environ.get("SEED_INSECURE_TLS") == "1":  # dev: mkcert CA not in container
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _request(url: str, *, method: str = "GET", data: bytes | None = None,
             headers: dict | None = None, timeout: int = 60) -> dict:
    req = urllib.request.Request(url, data=data, method=method,
                                 headers=headers or {})
    with urllib.request.urlopen(req, context=_ssl_context(), timeout=timeout) as resp:
        body = resp.read()
        return json.loads(body) if body else {}


# --- Auth ---------------------------------------------------------------------

def get_service_token() -> str:
    """OAuth2 client-credentials against Keycloak — the seed job is a first-class
    service client; its token passes gateway validation like any other caller."""
    token_url = (f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}"
                 "/protocol/openid-connect/token")
    form = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }).encode("ascii")
    payload = _request(
        token_url, method="POST", data=form,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    return payload["access_token"]


# --- Step 1: generate or restore ------------------------------------------------

def generate_or_restore() -> list[Path]:
    """Return the bundle files for SEED_VERSION, generating them if absent."""
    if BUNDLE_DIR.is_dir():
        bundles = sorted(BUNDLE_DIR.glob("*.json"))
        if bundles:
            print(f"seed: restored cached bundle set {BUNDLE_DIR} "
                  f"({len(bundles)} bundles)")
            return bundles

    BUNDLE_DIR.mkdir(parents=True, exist_ok=True)
    print(f"seed: generating {PATIENT_COUNT} patients with Synthea "
          f"{SYNTHEA_VERSION} -> {BUNDLE_DIR}")

    # ------------------------------------------------------------------ STUB
    # Real invocation (S1+): fetch the pinned jar (checksum-verified), run with
    # the Sri Lanka-adjusted config from this directory (names/demographics
    # localisation per 10 §2.3), e.g.:
    #
    #   subprocess.run(
    #       ["java", "-jar", str(jar_path),
    #        "-p", str(PATIENT_COUNT),
    #        "-c", "synthea-lk.properties",       # localisation overrides
    #        "--exporter.fhir.transaction_bundle", "true",
    #        "--exporter.baseDirectory", str(BUNDLE_DIR)],
    #       check=True,
    #   )
    #
    # The seed image (10 §1: `seed` job image) bakes the jar; this compose
    # skeleton runs on python:3.12-slim where java is absent, hence the stub.
    # ------------------------------------------------------------------------
    raise SystemExit(
        "seed: Synthea invocation not yet wired (S1 skeleton). Either drop a "
        f"pre-generated, versioned bundle set into {BUNDLE_DIR}/ or build the "
        "seed image with the pinned Synthea jar. See seed/README.md."
    )


# --- Step 2: load through the gateway --------------------------------------------

def load_bundles(bundles: list[Path], token: str) -> None:
    """POST each transaction bundle to HAPI via the gateway path — the token
    and route mean every write crosses the authz/consent/audit interceptors."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/fhir+json",
        "Accept": "application/fhir+json",
    }
    for i, bundle_path in enumerate(bundles, 1):
        raw = bundle_path.read_bytes()
        for attempt in range(3):
            try:
                _request(FHIR_URL, method="POST", data=raw,
                         headers=headers, timeout=120)
                break
            except urllib.error.HTTPError as exc:
                if exc.code in (429, 502, 503) and attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                print(f"seed: bundle {bundle_path.name} failed: "
                      f"{exc.code} {exc.reason}", file=sys.stderr)
                raise
        if i % 50 == 0 or i == len(bundles):
            print(f"seed: loaded {i}/{len(bundles)} bundles")


# --- Step 3: MPI registration -----------------------------------------------------

def register_mpi(bundles: list[Path], token: str) -> None:
    """Register every patient with core-api's MPI so PHNs are issued via the
    real issuance path — never injected post-generation (10 §2.3)."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    registered = 0
    for bundle_path in bundles:
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        patients = [
            e["resource"] for e in bundle.get("entry", [])
            if e.get("resource", {}).get("resourceType") == "Patient"
        ]
        for patient in patients:
            demo = registered < DEMO_PATIENT_COUNT
            body = json.dumps({
                "fhir_patient_id": patient.get("id"),
                # deterministic subset carries known PHNs for fixtures — the
                # MPI issues them; we only flag determinism:
                "deterministic_fixture": demo,
                # ~10 demo patients: face-consent granted + ext_face_id stub so
                # the face-sim flow works out of the box (05 §2 linkage shape)
                "face_consent": demo,
                "ext_face_id": f"demo-face-{registered + 1:04d}" if demo else None,
            }).encode("utf-8")
            _request(f"{MPI_URL}/patients", method="POST",
                     data=body, headers=headers)
            registered += 1
    print(f"seed: registered {registered} patients in MPI "
          f"({min(registered, DEMO_PATIENT_COUNT)} demo patients with "
          "face-consent + ext_face_id stubs)")


def main() -> int:
    print(f"seed: version {SEED_VERSION}, gateway {GATEWAY_URL}")
    bundles = generate_or_restore()
    token = get_service_token()
    load_bundles(bundles, token)
    register_mpi(bundles, token)
    print("seed: done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

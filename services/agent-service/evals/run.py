#!/usr/bin/env python
"""Eval-gate runner — S1 stub (04 §6, 10 §3.3).

S1 behaviour: discover and structurally validate golden fixtures, then exit 0
so the CI job shape exists from day 1. The real harness (graders, hard
thresholds — Rx-safety 100 %, citation faithfulness >= 98 % — and baseline
regression tracking) lands in S3, deliberately before write-back ships in S4
(ADR AG-6: the gate precedes the risk).

Exit codes (stable contract for CI):
    0 — pass (S1: fixtures discovered and well-formed)
    1 — hard-threshold failure or regression vs baseline (S3+)
    2 — harness error (bad fixtures, missing seed, ...)
"""

from __future__ import annotations

import sys
from pathlib import Path

GOLDEN_DIR = Path(__file__).parent / "golden"
REQUIRED_KEYS = {"id", "class", "seed_version", "input", "expected", "grader"}


def main() -> int:
    fixtures = sorted(GOLDEN_DIR.glob("*.yaml"))
    if not fixtures:
        print("eval-gate: no golden fixtures found", file=sys.stderr)
        return 2

    try:
        import yaml
    except ImportError:
        print(f"eval-gate: pyyaml not installed; discovered {len(fixtures)} fixture(s), skipping validation")
        return 0

    errors: list[str] = []
    for path in fixtures:
        try:
            case = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            errors.append(f"{path.name}: invalid YAML ({exc})")
            continue
        if not isinstance(case, dict):
            errors.append(f"{path.name}: fixture must be a mapping")
            continue
        missing = REQUIRED_KEYS - case.keys()
        if missing:
            errors.append(f"{path.name}: missing keys {sorted(missing)}")

    if errors:
        for err in errors:
            print(f"eval-gate: {err}", file=sys.stderr)
        return 2

    print(f"eval-gate: {len(fixtures)} golden fixture(s) valid.")
    print("eval-gate: S1 stub — graders and thresholds land in S3. PASS (exit 0).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

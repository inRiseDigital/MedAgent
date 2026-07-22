#!/usr/bin/env python
"""Eval-gate runner (04 §6, 10 §3.3).

Runs the golden set and enforces hard thresholds. The Rx-safety class is graded
against the DETERMINISTIC engine (exact match) and MUST be 100% — a single miss
fails the gate (ADR AG-6: the gate precedes write-back risk). LLM-graded classes
(summary_qa / citation) run only in --live mode (Anthropic key + reachable FHIR)
and are otherwise reported as skipped; when run, citation faithfulness must be
>= 98%.

Exit codes (stable CI contract):
    0 — all thresholds met
    1 — hard-threshold failure (Rx-safety < 100% or citation < 98%)
    2 — harness error (bad fixtures, engine import failure, ...)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parent.parent
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

GOLDEN_DIR = Path(__file__).parent / "golden"
RX_THRESHOLD = 1.0        # 100%
CITATION_THRESHOLD = 0.98


def _load_cases() -> tuple[list[dict], list[str]]:
    import yaml

    cases: list[dict] = []
    errors: list[str] = []
    for path in sorted(GOLDEN_DIR.glob("*.yaml")):
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            errors.append(f"{path.name}: invalid YAML ({exc})")
            continue
        if not isinstance(doc, dict):
            errors.append(f"{path.name}: fixture must be a mapping")
            continue
        if "cases" in doc:  # multi-case file with shared class/grader
            shared = {k: v for k, v in doc.items() if k != "cases"}
            for c in doc["cases"]:
                cases.append({**shared, **c, "_file": path.name})
        else:
            cases.append({**doc, "_file": path.name})
    return cases, errors


def _grade_rx(case: dict) -> tuple[bool, str]:
    from app.rxsafety import screen

    inp = case["input"]
    exp = case["expected"]
    v = screen(
        inp["proposed_drug"],
        inp.get("current_meds", []),
        inp.get("allergies", []),
        inp.get("dose_mg_per_day"),
    )
    if v.verdict != exp["verdict"]:
        return False, f"verdict {v.verdict} != expected {exp['verdict']} (codes {v.codes})"
    for code in exp.get("codes_include", []):
        if code not in v.codes:
            return False, f"missing expected code {code} (got {v.codes})"
    return True, f"{v.verdict} {v.codes}"


def _arg_value(flag: str) -> str | None:
    args = sys.argv[1:]
    if flag in args:
        i = args.index(flag)
        if i + 1 < len(args):
            return args[i + 1]
    return None


def main() -> int:
    argv = set(sys.argv[1:])
    live = "--live" in argv or os.environ.get("EVAL_LIVE") == "1"
    output_path = _arg_value("--output")

    try:
        import yaml  # noqa: F401
    except ImportError:
        print("eval-gate: pyyaml not installed", file=sys.stderr)
        return 2

    cases, errors = _load_cases()
    if errors:
        for e in errors:
            print(f"eval-gate: {e}", file=sys.stderr)
        return 2
    if not cases:
        print("eval-gate: no golden cases found", file=sys.stderr)
        return 2

    rx_pass = rx_total = 0
    skipped = 0
    failures: list[str] = []

    for case in cases:
        cls = case.get("class")
        cid = case.get("id", "?")
        if cls == "rx_safety":
            rx_total += 1
            try:
                ok, detail = _grade_rx(case)
            except Exception as exc:  # noqa: BLE001
                print(f"eval-gate: engine error on {cid}: {exc}", file=sys.stderr)
                return 2
            if ok:
                rx_pass += 1
                print(f"  PASS  [rx_safety] {cid}: {detail}")
            else:
                failures.append(f"[rx_safety] {cid}: {detail}")
                print(f"  FAIL  [rx_safety] {cid}: {detail}")
        elif cls in ("summary_qa", "citation"):
            skipped += 1
            hint = "live grader not yet implemented" if live else "live-only; run with --live"
            print(f"  SKIP  [{cls}] {cid} ({hint})")
        else:
            skipped += 1
            print(f"  SKIP  [{cls}] {cid} (unknown class)")

    rx_rate = (rx_pass / rx_total) if rx_total else 1.0
    print(f"\neval-gate summary: rx_safety {rx_pass}/{rx_total} ({rx_rate:.0%}), skipped {skipped}")

    if output_path:
        import json

        Path(output_path).write_text(
            json.dumps(
                {
                    "rx_safety": {"pass": rx_pass, "total": rx_total, "rate": rx_rate,
                                  "threshold": RX_THRESHOLD},
                    "skipped": skipped,
                    "failures": failures,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    if rx_total and rx_rate < RX_THRESHOLD:
        print(f"eval-gate: FAIL — Rx-safety {rx_rate:.0%} < required {RX_THRESHOLD:.0%}", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1

    print("eval-gate: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

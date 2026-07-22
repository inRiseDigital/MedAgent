"""Deterministic Rx-safety engine (04 §7 / ADR AG-2, agents/03-rx-safety).

The SAFETY VERDICT IS COMPUTED HERE, deterministically — never by the LLM. The
LLM may only narrate this verdict. The engine screens a proposed drug against the
patient's current medications and allergies using a clinician-curated, versioned
dataset (drug classes, DDI pairs, dose ranges) keyed by normalized ingredient
(production keys by RxCUI with RxClass/ATC).

INVARIANTS:
- Fail closed: if the dataset cannot load, every prescription is BLOCKED
  (DATASET_UNAVAILABLE) — never silently passed.
- block  = documented allergy (ingredient) match, allergy hard-class match, a
           contraindicated or major DDI.
- warn   = partial cross-reactivity (e.g. penicillin allergy -> cephalosporin),
           a moderate DDI, or a dose over the reference maximum. Warnings are
           overridable by the clinician with a mandatory audited reason (04).
- pass   = nothing found.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_DATA = Path(__file__).parent / "data"

# Allergy classes where sharing the class is itself a contraindication (block),
# vs. partial/uncertain cross-reactivity (warn).
_HARD_ALLERGY_CLASSES = {"penicillin", "sulfonamide", "nsaid"}
_PARTIAL_CROSS = {
    # documented-allergy-class -> proposed-class that warrants a WARN (not block)
    ("penicillin", "cephalosporin"),
}


@dataclass
class Verdict:
    verdict: str  # "pass" | "warn" | "block"
    codes: list[str] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)
    dataset_version: str = ""
    proposed: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "codes": self.codes,
            "findings": self.findings,
            "dataset_version": self.dataset_version,
            "proposed": self.proposed,
        }


class _Dataset:
    """Loads + holds the curated dataset. `ok` is False if anything failed to load."""

    def __init__(self) -> None:
        self.ok = False
        self.drugs: dict[str, dict[str, Any]] = {}
        self.rules: list[dict[str, Any]] = []
        self.doses: dict[str, float] = {}
        self.version = "unloaded"
        self._load()

    def _load(self) -> None:
        try:
            classes = json.loads((_DATA / "drug_classes.json").read_text(encoding="utf-8"))
            inter = json.loads((_DATA / "interactions.json").read_text(encoding="utf-8"))
            doses = json.loads((_DATA / "dose_ranges.json").read_text(encoding="utf-8"))
            self.drugs = classes["drugs"]
            self.rules = inter["rules"]
            self.doses = doses["adult_max_daily_mg"]
            self.version = f'{classes.get("_version")}|{inter.get("_version")}|{doses.get("_version")}'
            self.ok = True
        except Exception:  # noqa: BLE001 — any load failure -> fail closed
            self.ok = False


_DS = _Dataset()


def _normalize(name: str) -> dict[str, Any]:
    """Map a free-text drug name to {ingredient, classes}. Unknown -> bare ingredient."""
    key = re.sub(r"\s+", " ", name.strip().lower())
    key = re.split(r"[ /]", key)[0] if key not in _DS.drugs else key
    entry = _DS.drugs.get(key) or _DS.drugs.get(name.strip().lower())
    if entry:
        return {"ingredient": entry["ingredient"], "classes": set(entry.get("classes", [])), "known": True}
    return {"ingredient": key, "classes": set(), "known": False}


def _tokens(norm: dict[str, Any]) -> set[str]:
    return {norm["ingredient"], *norm["classes"]}


def screen(
    proposed_drug: str,
    current_meds: list[str],
    allergies: list[dict[str, Any]],
    dose_mg_per_day: float | None = None,
) -> Verdict:
    """Compute the deterministic safety verdict for `proposed_drug`."""
    # Fail closed.
    if not _DS.ok:
        return Verdict(
            verdict="block",
            codes=["DATASET_UNAVAILABLE"],
            findings=[{"code": "DATASET_UNAVAILABLE", "severity": "block",
                       "rationale": "Drug-safety dataset unavailable — prescribing is blocked (fail-closed, 04 §7)."}],
            dataset_version=_DS.version,
            proposed=proposed_drug,
        )

    prop = _normalize(proposed_drug)
    findings: list[dict[str, Any]] = []

    # 1. Allergy checks -----------------------------------------------------
    for alg in allergies:
        sub = str(alg.get("substance", ""))
        if not sub:
            continue
        anorm = _normalize(sub)
        crit = alg.get("criticality", "unknown")
        if prop["ingredient"] == anorm["ingredient"] and prop["ingredient"]:
            findings.append({"code": "ALLERGY_MATCH", "severity": "block",
                             "rationale": f"Proposed drug matches a documented allergy: {sub} (criticality {crit}).",
                             "against": sub})
            continue
        shared = prop["classes"] & anorm["classes"]
        hard = shared & _HARD_ALLERGY_CLASSES
        if hard:
            findings.append({"code": "ALLERGY_CLASS", "severity": "block",
                             "rationale": f"Same allergy class as documented allergy {sub}: {', '.join(sorted(hard))} (criticality {crit}).",
                             "against": sub})
        else:
            for a_cls in anorm["classes"]:
                for p_cls in prop["classes"]:
                    if (a_cls, p_cls) in _PARTIAL_CROSS:
                        findings.append({"code": "ALLERGY_CROSS", "severity": "warn",
                                         "rationale": f"Partial cross-reactivity: documented {a_cls} allergy ({sub}) vs proposed {p_cls}.",
                                         "against": sub})

    # 2. Drug-drug interactions --------------------------------------------
    ptoks = _tokens(prop)
    for med in current_meds:
        mnorm = _normalize(med)
        mtoks = _tokens(mnorm)
        for rule in _DS.rules:
            a, b = rule["a"], rule["b"]
            if (a in ptoks and b in mtoks) or (b in ptoks and a in mtoks):
                findings.append({"code": rule["code"], "severity":
                                 "block" if rule["severity"] in ("contraindicated", "major") else "warn",
                                 "ddi_severity": rule["severity"],
                                 "rationale": f"{rule['rationale']} (with current {med})",
                                 "against": med})

    # 3. Dose range ---------------------------------------------------------
    if dose_mg_per_day is not None and prop["ingredient"] in _DS.doses:
        max_daily = _DS.doses[prop["ingredient"]]
        if dose_mg_per_day > max_daily:
            findings.append({"code": "DOSE_EXCEEDED", "severity": "warn",
                             "rationale": f"Proposed {dose_mg_per_day} mg/day exceeds the adult reference maximum {max_daily} mg/day for {prop['ingredient']}."})

    severities = {f["severity"] for f in findings}
    verdict = "block" if "block" in severities else "warn" if "warn" in severities else "pass"
    if not prop["known"] and verdict == "pass":
        findings.append({"code": "UNKNOWN_DRUG", "severity": "warn",
                         "rationale": f"'{proposed_drug}' is not in the curated dataset — screening is incomplete; verify manually."})
        verdict = "warn"

    return Verdict(
        verdict=verdict,
        codes=sorted({f["code"] for f in findings}),
        findings=findings,
        dataset_version=_DS.version,
        proposed=proposed_drug,
    )

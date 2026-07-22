# Eval candidates — human review queue (governed learning loop)

`app/learning/analyze.py` writes **candidate** eval cases here from captured
feedback (clinician thumbs-down, rejected/overridden proposals). They are
**proposals for a human**, not part of the gate.

Workflow:
1. A reviewer (clinician for `rx_safety_review`, engineer for `summary_qa`)
   inspects the candidate.
2. If it reflects a real gap, they author a proper golden case in
   `evals/golden/` (and, for a drug-safety change, a **clinician-reviewed PR**
   to `app/rxsafety/data/`).
3. The eval gate (`evals/run.py`) then grades it. Only changes that pass the
   gate merge.

**Governance:** nothing here changes runtime behaviour. The deterministic
Rx-safety engine and its dataset are never auto-modified — `rx_safety_review`
candidates are prompts for pharmacist review, not edits. The generated `*.json`
candidates are gitignored (ephemeral review queue); this README is tracked.

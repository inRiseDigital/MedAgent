# Golden evaluation set (S1 seed)

This directory holds the **golden set** of graded cases that gates CI for
agent-service (04 §6, spec §4.4, 10 §3.3). It is the S1 seed of a set that
must reach **≥ 150 graded cases by S3** and grows continuously from clinician
feedback (weekly curation turns signed/edited/rejected outcomes and 👍/👎
reports into new cases first).

## How the gate works

- Any PR touching prompts (`prompts/`), tools, graph topology, the model pin,
  or the DDI dataset runs the full golden set in CI.
- Hard thresholds, enforced as a required status check with the same standing
  as failing unit tests:
  - **Rx-safety fixtures: 100 %** — known DDI/allergy cases must all produce
    the expected verdict (these are checked by deterministic code, so 100 % is
    a code guarantee, not an aspiration).
  - **Citation faithfulness: ≥ 98 %.**
  - **No regression vs the `main` baseline** — a regression blocks merge.
- Results (pass rate, cost, latency percentiles per case class) are posted as
  a PR comment and pushed to the eval dashboard.
- **Models never self-update in production**: model-pin bumps are PRs with
  eval evidence; rollback is a config revert.

## Case classes (target mix per 04 §6)

summary QA over pinned Synthea seed data · citation faithfulness ·
Rx-safety verdicts (DDI/allergy fixtures) · prompt-injection probes ·
refusal cases · Sinhala/Tamil name handling.

## Fixture format

One YAML file per case (see the two examples in this directory):

```yaml
id: unique-case-id
class: summary_qa | citation | rx_safety | injection | refusal | name_handling
seed_version: v0        # Synthea seed the case was graded against (10 §2.3)
input: {...}            # case-class-specific input
expected: {...}         # expected outcome
grader: exact | llm_rubric   # exact for verdicts; human-audited rubric for prose
```

## Running

```bash
python evals/run.py          # exits non-zero on any hard-threshold failure
```

S1 status: the runner is a stub (loads fixtures, exits 0). The real harness,
graders, and baseline tracking land in S3 — deliberately **before** write-back
ships in S4 (ADR AG-6: the gate precedes the risk).

# CI home (infra/ci)

Per 10-devops-infrastructure.md §3 this directory is the referenced home for
CI logic. GitHub only executes workflow files from `.github/workflows/`
(symlinks are not reliably followed by Actions on all runners), so the split
is:

| Where | What |
|---|---|
| `.github/workflows/ci.yml` | PR pipeline: change detection (dorny/paths-filter), per-package lint/type/test jobs, ts-sdk contract check, gitleaks |
| `.github/workflows/eval-gate.yml` | AI eval gate — required check on agent-service prompt/tool/graph/model-pin/dataset changes (10 §3.3) |
| `.github/workflows/build-images.yml` | merge-to-main: build, Trivy, SBOM (syft), cosign keyless sign, push GHCR `{sha}` (10 §3.5) |
| `infra/ci/actions/*` | shared composite actions referenced from workflows via `uses: ./infra/ci/actions/<name>` |

Conventions:

- Workflow changes and composite-action changes review together — treat this
  directory and `.github/workflows/` as one unit.
- Required checks on `main` (10 §3.6): all per-package jobs, integration,
  eval gate (when triggered), gitleaks, Trivy config scan. Configure in branch
  protection when the repo goes live on GitHub.
- No secrets in workflows; deploy-time secrets are SOPS-managed
  (`infra/secrets/`), CI-side secrets are GitHub environment secrets only.

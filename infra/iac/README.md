# Infrastructure as Code (placeholder — lands S6-adjacent)

Per 10-devops-infrastructure.md §4: **no environment is hand-built**. This
directory will hold the OpenTofu modules + Ansible plays that define the
shared-dev, staging, and pilot environments (01 §6). Nothing here is
implemented in S1; the layout below is the agreed shape so other work can
reference stable paths.

## Planned layout

```
infra/iac/
├── modules/                  # reusable, environment-agnostic
│   ├── network/              # VPC/subnets/firewalling, edge exposure for gateway only
│   ├── compute/              # VM/node provisioning (compose or single-node k3s, ADR DI-2)
│   ├── postgres/             # managed Postgres or Patroni wiring; pgBackRest hooks (§7)
│   ├── dns-tls/              # DNS records + ACME/Traefik TLS (where cloud-hosted)
│   └── observability/        # standing Grafana/Tempo/Loki/Prometheus for staging/pilot
├── envs/
│   ├── dev/                  # 1× small VM/node, deployed on merge to main
│   ├── staging/              # prod-shaped: 1× replica/service, HA-configured Postgres
│   └── pilot/                # 2× app replicas, HA Postgres, Redis sentinel, backups
└── ansible/                  # on-VM composition where pilot lands on hospital hardware
```

## Rules (from 10 §4/§5)

- Environment-specific values (endpoints, replica counts) live here; **secrets
  never do** — SOPS-encrypted files in `infra/secrets/` are decrypted at
  release time and injected as runtime env.
- Drift detection: weekly `tofu plan` in CI with diff alerts.
- Deploys promote the *same image digest* between environments (10 §3.5);
  pilot applies only via the protected GitHub environment.
- The modules are the unit of portability for Phase B (government substrate
  per NDHX direction) — same containers, new substrate.

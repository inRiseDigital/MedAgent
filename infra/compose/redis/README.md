# Redis ACL users

`users.acl` defines per-service Redis users with least privilege (10 §5).
**DEV PASSWORDS ONLY** — real environments receive a SOPS-rendered ACL file at
deploy time (`infra/secrets/`); this file must never contain real credentials.

## Format constraint

Redis loaded via `--aclfile` uses the strict external ACL format: the file may
contain **only `user ...` directives** — no comments, no blank lines. Adding a
`#` comment makes Redis abort startup ("should start with user keyword"). Keep
the documentation here, not in the file.

## Users

| User | Purpose |
|---|---|
| `default` | Healthcheck probe only — `+ping`, no keys, no password. |
| `core-api` | Keys `core:* queue:* rate:* consent:* authz:* face:*` (authz decision cache, face-webhook idempotency); publishes channels `events:checkin:* events:consent:*`. |
| `agent-service` | Own cache/session keys (`agent:*`); subscribes to `events:consent:*`. |
| `notify-service` | Keys `notify:* sse:ticket:*` (SSE ticket issue/redeem); subscribes to `events:checkin:* events:user:* events:consent:*`. |

Channel conventions (01 §1 / §4.1): all pub/sub channels live under the
`events:` namespace — `events:checkin:{facility}` published by core-api and
consumed by notify-service, `events:user:{sub}` personal streams, and
`events:consent:*` the cache-invalidation fan-out. Key namespaces match the
templates in the services (`authz:{actor}:{patient}`, `face:event:{id}`,
`sse:ticket:{id}`).

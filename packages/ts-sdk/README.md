# @medagent/ts-sdk

OpenAPI-generated TypeScript clients and typed fetch wrappers for the three
platform services. This package is the **only HTTP surface** for `apps/web`
(docs/solution/06 ADR W-5, §8 rule 3) — hand-written `fetch` is lint-banned
outside the two BFF proxy routes.

## Generation

```sh
pnpm --filter @medagent/ts-sdk generate
```

Runs `openapi-typescript` against each service's FastAPI-exported schema:

| Service | Default URL | Env override |
|---|---|---|
| core-api | `http://localhost:8001/openapi.json` | `CORE_API_OPENAPI_URL` |
| agent-service | `http://localhost:8002/openapi.json` | `AGENT_SERVICE_OPENAPI_URL` |
| notify-service | `http://localhost:8003/openapi.json` | `NOTIFY_SERVICE_OPENAPI_URL` |

Output: `src/generated/{core-api,agent-service,notify-service}.ts`.

## CI contract rule (docs/solution/10 §3.2)

The **contract-gen check** in CI regenerates the clients from each service's
exported OpenAPI schema and runs `git diff --exit-code`:

- A service API change **without** a regenerated, committed SDK **fails the
  build**. Contract drift is a build failure, not a runtime surprise.
- **Never hand-edit files under `src/generated/`** — they are overwritten on
  every generation, and any hand edit is exactly the drift the check exists
  to catch. Wrapper/helper code belongs in `src/index.ts` (or new
  non-generated modules).
- Generated files are committed; consumers import types via
  `@medagent/ts-sdk/generated/<service>`.

## Usage

```ts
import { createClient } from "@medagent/ts-sdk";
import type { paths as CoreApiPaths } from "@medagent/ts-sdk/generated/core-api";

const coreApi = createClient<CoreApiPaths>({
  baseUrl: process.env.CORE_API_URL!,
  headers: async () => ({ authorization: `Bearer ${await sessionAccessToken()}` }),
});
```

S1 note: per-operation response narrowing (openapi-fetch-grade typing) is
completed in S2 once the first generated schemas are committed
(docs/solution/11 S1–S2).

/**
 * Contract generation — FastAPI OpenAPI schemas -> src/generated/*.ts
 * (docs/solution/01 §2, 10 §3.2).
 *
 * Each service exports its schema at /openapi.json (FastAPI default).
 * URLs are env-overridable so CI can point at schemas exported from the
 * compose stack or at committed schema files.
 *
 * CI contract rule (10 §3.2): the contract-gen check regenerates these
 * clients and runs `git diff --exit-code` — a service API change without a
 * regenerated, committed SDK fails the build. See README.md.
 */
import { execFileSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");

const services = [
  {
    name: "core-api",
    url: process.env.CORE_API_OPENAPI_URL ?? "http://localhost:8001/openapi.json",
  },
  {
    name: "agent-service",
    url: process.env.AGENT_SERVICE_OPENAPI_URL ?? "http://localhost:8002/openapi.json",
  },
  {
    name: "notify-service",
    url: process.env.NOTIFY_SERVICE_OPENAPI_URL ?? "http://localhost:8003/openapi.json",
  },
];

mkdirSync(resolve(root, "src/generated"), { recursive: true });

let failed = false;
for (const { name, url } of services) {
  const out = resolve(root, `src/generated/${name}.ts`);
  console.log(`[ts-sdk] generating ${name} from ${url}`);
  try {
    // openapi-typescript CLI ships with this package's devDependencies.
    execFileSync("npx", ["--no-install", "openapi-typescript", url, "-o", out], {
      cwd: root,
      stdio: "inherit",
      shell: process.platform === "win32",
    });
  } catch (err) {
    failed = true;
    console.error(`[ts-sdk] FAILED for ${name}: ${err.message ?? err}`);
  }
}

if (failed) {
  console.error(
    "[ts-sdk] generation incomplete — is the compose stack up (docker compose up), " +
      "or are *_OPENAPI_URL env vars pointing at exported schema files?",
  );
  process.exit(1);
}

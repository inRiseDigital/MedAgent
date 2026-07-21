# syntax=docker/dockerfile:1
# Web (Next.js 16) image. BUILD CONTEXT IS THE REPO ROOT (see compose) so the
# pnpm workspace packages (@medagent/ui, @medagent/ts-sdk) resolve. Multi-stage
# per 10 §1: deps layer is cache-friendly on manifests; dev target runs the
# Next dev server with source bind-mounted by compose.

FROM node:22-alpine AS base
ENV PNPM_HOME=/pnpm PATH="/pnpm:$PATH"
RUN corepack enable
WORKDIR /repo

# ---- deps: install the whole workspace from manifests only (layer-cached) ----
FROM base AS deps
COPY pnpm-workspace.yaml package.json ./
COPY pnpm-lock.yaml* ./
COPY apps/web/package.json apps/web/package.json
COPY packages/ui/package.json packages/ui/package.json
COPY packages/ts-sdk/package.json packages/ts-sdk/package.json
# No committed lockfile yet (S1) — resolve fresh; --frozen-lockfile lands once
# pnpm-lock.yaml is committed (CI enforces it, 10 §3.2).
RUN pnpm install

# ---- dev target: source is bind-mounted by compose; node_modules stays in
#      the image via anonymous volumes (10 §2.1) ----
FROM deps AS dev
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
EXPOSE 3000
CMD ["pnpm", "--filter", "@medagent/web", "dev", "--port", "3000", "--hostname", "0.0.0.0"]

# ---- build + runtime (standalone) for staging/pilot ----
FROM deps AS build
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
RUN pnpm --filter @medagent/web build

FROM node:22-alpine AS runtime
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
WORKDIR /app
# Next standalone output (apps/web/next.config.ts must set output: "standalone").
COPY --from=build /repo/apps/web/.next/standalone ./
COPY --from=build /repo/apps/web/.next/static ./apps/web/.next/static
COPY --from=build /repo/apps/web/public ./apps/web/public
USER 10001
EXPOSE 3000
CMD ["node", "apps/web/server.js"]

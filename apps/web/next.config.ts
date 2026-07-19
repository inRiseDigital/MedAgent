import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

// next-intl request config (docs/solution/06 §9 — i18n scaffolded day 1).
const withNextIntl = createNextIntlPlugin("./i18n/request.ts");

const nextConfig: NextConfig = {
  // Workspace packages are consumed as TypeScript source (no build step).
  transpilePackages: ["@medagent/ui", "@medagent/ts-sdk"],
  // Turbopack is the Next 16 default bundler — no flag needed.
  // Route protection lives in proxy.ts (Next 16 name for middleware, 06 §1/§2).
};

export default withNextIntl(nextConfig);

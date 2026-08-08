import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

// next-intl request config (docs/solution/06 §9 — i18n scaffolded day 1).
const withNextIntl = createNextIntlPlugin("./i18n/request.ts");

const nextConfig: NextConfig = {
  // Workspace packages are consumed as TypeScript source (no build step).
  transpilePackages: ["@medagent/ui", "@medagent/ts-sdk"],
  // Turbopack is the Next 16 default bundler — no flag needed.
  // Route protection lives in proxy.ts (Next 16 name for middleware, 06 §1/§2).
  //
  // DEV over a public tunnel (scripts/share-demo.sh): Next's dev server blocks
  // cross-origin dev/HMR requests (the webpack-hmr websocket) from any host not
  // listed here. When the app is reached at a *.trycloudflare.com / *.ngrok
  // hostname, that block silently stalls client hydration — the page renders but
  // nothing is interactive. Allow the tunnel hosts so HMR connects and the app
  // hydrates. (No effect on production, which has no HMR.)
  allowedDevOrigins: ["*.trycloudflare.com", "*.ngrok-free.app", "*.ngrok.io", "localhost"],
};

export default withNextIntl(nextConfig);

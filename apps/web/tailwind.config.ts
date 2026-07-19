/**
 * Tailwind config (loaded via `@config` in app/globals.css — Tailwind v4
 * JS-config compatibility). All semantic colour/typography comes from the
 * shared @medagent/ui preset; this file adds nothing palette-shaped
 * (docs/solution/06 §4.2, ADR W-3).
 */
import medagentPreset from "@medagent/ui/tailwind-preset";

const config = {
  presets: [medagentPreset],
  content: [
    "./app/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
    "../../packages/ui/src/**/*.{ts,tsx}",
  ],
};

export default config;

/**
 * MedAgent Tailwind preset — maps the semantic CSS custom properties from
 * styles/tokens.css into Tailwind theme keys, so components write
 * `bg-card text-foreground border-border` and never hard-code palette values
 * (docs/solution/06 §4.2, ADR W-3).
 *
 * Consumed by apps/web via `presets: [medagentPreset]` in its Tailwind
 * config (loaded through Tailwind v4's `@config` compatibility layer).
 * Dark mode is the class/selector strategy on [data-theme="dark"] — matching
 * tokens.css — so `dark:` variants work for the genuinely asymmetric cases.
 */
const medagentPreset = {
  darkMode: ["selector", '[data-theme="dark"]'],
  theme: {
    extend: {
      fontFamily: {
        // Consume the semantic font tokens (tokens.css → next/font). `font-sans`
        // is the default body face; `font-mono` is for tabular data + citations.
        sans: ["var(--font)"],
        mono: ["var(--font-mono)"],
      },
      colors: {
        background: "var(--background)",
        foreground: "var(--foreground)",
        card: {
          DEFAULT: "var(--card)",
          foreground: "var(--card-foreground)",
        },
        muted: {
          DEFAULT: "var(--muted)",
          foreground: "var(--muted-foreground)",
        },
        border: {
          DEFAULT: "var(--border)",
          strong: "var(--border-strong)",
        },
        ring: "var(--ring)",
        primary: {
          DEFAULT: "var(--primary)",
          foreground: "var(--primary-foreground)",
        },
        destructive: {
          DEFAULT: "var(--destructive)",
          foreground: "var(--destructive-foreground)",
          surface: "var(--destructive-surface)",
        },
        warning: {
          DEFAULT: "var(--warning)",
          foreground: "var(--warning-foreground)",
          surface: "var(--warning-surface)",
        },
        success: {
          DEFAULT: "var(--success)",
          foreground: "var(--success-foreground)",
          surface: "var(--success-surface)",
        },
        verdict: {
          pass: "var(--verdict-pass)",
          warn: "var(--verdict-warn)",
          block: "var(--verdict-block)",
        },
      },
      /*
       * Type scale per 06 §4.3: 12/13/14/16/18/22/28 px steps.
       * 14 px body for clinical data density (doctor workspace);
       * 16 px body in patient-portal contexts (07 §2).
       */
      fontSize: {
        "2xs": ["0.75rem", { lineHeight: "1rem" }], // 12
        xs: ["0.8125rem", { lineHeight: "1.125rem" }], // 13
        sm: ["0.875rem", { lineHeight: "1.25rem" }], // 14 — clinical body
        base: ["1rem", { lineHeight: "1.5rem" }], // 16 — portal body
        lg: ["1.125rem", { lineHeight: "1.625rem" }], // 18
        xl: ["1.375rem", { lineHeight: "1.75rem" }], // 22
        "2xl": ["1.75rem", { lineHeight: "2.125rem" }], // 28
      },
      /* 8-px spacing grid and 1-px-border card language come from defaults;
         compact 40–44 px row heights are per-component (06 §4.3). */
    },
  },
};

export default medagentPreset;

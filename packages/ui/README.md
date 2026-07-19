# @medagent/ui

MedAgent design system: semantic tokens + presentational components.
Governing document: `docs/solution/06-doctor-workspace-frontend.md` §4 and §8.

## What lives here

- `styles/tokens.css` — the single source of truth for colour/typography in
  **both** themes: semantic CSS custom properties on `:root`, dark values on
  `:root[data-theme="dark"]`.
- `tailwind-preset.ts` — maps those variables into Tailwind theme keys
  (`bg-card`, `text-foreground`, `text-verdict-warn`, …).
- `src/` — presentational components, exported through `src/index.ts`.

## Component rules (enforced by lint/CI where possible, review otherwise)

1. **Max ~200 lines / one responsibility per component file.** The
   prototype's 859-line `PatientChat.tsx` is the canonical counter-example
   (06 §8 rule 1, ADR W-8).
2. **Presentational purity**: components here are props-in/JSX-out. No data
   fetching, no stores, no `@medagent/ts-sdk` imports — containers in
   `apps/web` bind them to queries, streams and stores (06 §8 rule 2).
   This is what makes Storybook + axe coverage cheap.
3. **Semantic utilities only**: `bg-card`, `text-muted-foreground`, never
   `bg-white` / `text-gray-*` (lint-warned) and never `!important`
   (lint-banned — ADR W-3).
4. **Accessibility**: focus-visible ring on every interactive element,
   never colour alone (icon or label always accompanies severity/status
   colour), WCAG 2.1 AA contrast for every token pair in both themes
   (06 §4.5). axe assertions per Storybook story land with the Storybook
   setup (S2+).
5. Shared presentational pieces graduate here from `apps/web` **on second
   use only** (06 §8 rule 5).

S1 scaffold ships Button, Card, Badge (verdict variants pass/warn/block),
Spinner. The full Phase A inventory (06 §4.4 — chips, proposal card,
citation chip, banners, toasts, skeletons, …) lands S2–S4 per
`docs/solution/11-sprint-plan-phase-a.md`.

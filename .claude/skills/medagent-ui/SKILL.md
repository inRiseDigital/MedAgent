---
name: medagent-ui
description: MedAgent's design language + world-class UI/UX principles for any interface work in this repo — building or reshaping the patient portal, doctor cockpit, generative-UI widgets, theming, motion, or accessibility. Use whenever you touch apps/web or packages/ui, or design a new screen, component, widget, flow, or the theme. Grounds every choice in MedAgent's real tokens + clinical constraints so the result is best-in-class AND consistent. Pair with the `frontend-design` skill for aesthetic direction on net-new surfaces.
---

# MedAgent UI

Design like the lead of a studio whose one client is a **national medical platform**. The bar is world-class *and* clinical: **premium comes from clarity, consistency, and trustworthy status — never decoration.** A clinician scanning a record under time pressure and a first-time patient with no AI literacy must both succeed. When designing a net-new surface, also load `frontend-design` for aesthetic direction; this skill supplies the MedAgent system and the guardrails.

## Non-negotiables (these outrank aesthetics)
1. **Safety is topology, not style.** Never style a blocked/critical state into something dismissible. A `block` Rx verdict, an `escalation`, a `safety-alert` must read as unmistakable and cannot be visually softened into a normal action.
2. **Severity is never color alone** (WCAG 1.4.1). Every status carries icon + text + shape, so it survives color-blindness, grayscale, and glare on a ward screen.
3. **Everything cited.** Clinical claims render with a `[source: Type/id]` chip; web results are visually distinct and never mixed into record citations.
4. **WCAG 2.2 AA is the floor**, both themes: ≥4.5:1 text / ≥3:1 UI contrast, visible `:focus-visible` rings, keyboard paths, `prefers-reduced-motion` honored, non-color cues, reflow/zoom. Verify contrast against the pairs actually rendered, not by eye.
5. **Propose-then-commit is visible.** A model proposal looks like a proposal (a `confirm-action` the user taps); it must never masquerade as a committed fact.

## The design system (use these tokens — never raw hex in components)
- **Source of truth:** `packages/ui/styles/tokens.css` (semantic tokens, light + dark) and `apps/web/app/mh-theme.css` (the premium `.mh` component skin, token-driven). `packages/ui/tailwind-preset.ts` maps tokens → utilities. `!important` is lint-banned.
- **Theme is light/dark/system.** Bare `:root` = light; `@media (prefers-color-scheme: dark)` guarded by `:root:not([data-theme="light"])`; `:root[data-theme="dark"]` for the explicit toggle. Style through semantic tokens only — never define a color solely inside a media/`[data-theme]` block. `body` sets an explicit token background.
- **Palette identity:** teal accent — `--primary` `#0f766e` (light) / `#2dd4bf`–`#0f9d8c` (dark). Neutrals are **slate** (cool, biased toward the accent — never pure grey). Semantic success/warning/danger are reserved for clinical meaning and are *separate from* the accent. Health-metric category palette: heart · activity · body · resp · nutri · mind.
- **Type:** Inter (display + body) + JetBrains Mono (data, citations, tokens), via `next/font` (`--font` / `--font-mono`). Set a type scale and stay on it; headings get `text-wrap: balance`; data columns get `tabular-nums`.
- **Motion:** tokens `--dur-*` + `--ease-*` drive rise-in, hover lift, press feedback, thinking pulse, confirm→done. Prefer transform/opacity (GPU). Everything disabled under `prefers-reduced-motion` at the source. Motion is feedback, not spectacle — no marketing-page flash in clinical surfaces.
- **Widgets:** the generative-UI registry in `apps/web/components/widgets.tsx` (~15 kinds: safety-alert, escalation, record-links, metric-trend, stat-grid, next-best-action, timeline, summary, confirm-action, access-log, consent-panel, consult-session, order-status, receipt, plan-steps). New agent output renders through this registry; `confirm-action` and `escalation` are NOT model-forgeable.

## Principles that raise the ceiling (apply, don't cite)
- **Refactoring UI:** design hierarchy with weight/size/color before borders; constrained spacing/type/shadow scales; lift the *one* element that matters instead of a card+shadow on everything; not everything is a card; establish grayscale, add color last for meaning.
- **Laws of UX:** Jakob's (match clinical-software conventions clinicians already know) · Fitts's (make the primary action big and reachable; destructive actions are not adjacent to it) · Hick's (reduce choices at the point of decision — a confirm card shows one clear action) · Aesthetic-usability (polish earns trust, which matters double in health) · Doherty (respond < 400ms perceptually — stream a status/thinking state immediately so the UI never feels dead).
- **Information design for the cockpit:** it's scanned and operated, not read. Surface the summary before detail; encode state in form (pill, chip, severity stripe) so what needs attention reads at a glance; keep a persistent patient banner (name, allergies, key flags) during an encounter.
- **Clinical states are distinct labels** — patient-reported vs imported vs AI-extracted vs clinician-reviewed vs signed vs amended never look the same; an AI-extracted value is visibly *unverified* until a clinician reviews it.
- **Honest empty/error states:** "No records added yet" (never imply a missing test is a normal result); "Not completed" vs "Still confirming" — recover status before asking the user to retry a consequential action.
- **Localisation:** En/Si/Ta with human-reviewed strings, mixed-script search, locale dates (Asia/Colombo), and fonts whose glyph coverage is verified for Sinhala/Tamil — never assume a Latin face covers them.

## Working method
1. Read the existing tokens/skin/widget first; extend, never fork the system.
2. State a one-line design intent (what changes, for whom, the single job) before coding.
3. Build token-driven, both themes, reduced-motion-guarded, keyboard+SR accessible.
4. Verify: `docker exec medagent-web-1 sh -lc 'cd /repo/apps/web && npx tsc --noEmit && npx vitest run'` (0 non-`.next` tsc errors, vitest green); contrast checked programmatically over rendered pairs; app serves 200. Web edits need the webpack+polling dev server / a web-container recreate to show (see the web-dev-hot-reload note).
5. For a shareable review of a look, publish a style-guide/mockup artifact rather than only describing it.

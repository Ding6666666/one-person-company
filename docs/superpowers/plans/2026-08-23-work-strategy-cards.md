# Work Strategy Cards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the work strategy select with accessible, colorful, explanatory cards while preserving every existing strategy payload and validation rule.

**Architecture:** Define strategy presentation metadata next to `StrategyComposer`, render it through one card-selector component, and keep the existing conditional configuration fields untouched. Put all visual behavior in the current work CSS module and verify selection through accessible button semantics.

**Tech Stack:** React 18, TypeScript, CSS Modules, Vitest, Testing Library

---

### Task 1: Lock the strategy-card interaction with tests

**Files:**
- Modify: `apps/dsh-company-plugin/tests/work-graph.client.spec.tsx`

- [ ] Add a failing test that renders `StrategyComposer` in Chinese and asserts four strategy buttons, Direct selected by default, all summaries visible, only the Direct detailed explanation visible, and no Strategy combobox.
- [ ] Click Battle and assert `aria-pressed`, Battle details, participant controls, and the absence of Direct-only employee configuration.
- [ ] Run `pnpm exec vitest run tests/work-graph.client.spec.tsx --reporter=dot` from `apps/dsh-company-plugin` and confirm RED.

### Task 2: Implement strategy metadata and cards

**Files:**
- Modify: `apps/dsh-company-plugin/src/client/StrategyComposer.tsx`
- Modify: `apps/dsh-company-plugin/src/client/Work.module.css`

- [ ] Add localized metadata for name, summary, workflow, suitable use, required configuration, and unsuitable use for all four strategies.
- [ ] Replace the strategy `<select>` with a labelled button grid using `aria-pressed` and a selected detail region.
- [ ] Keep strategy state, validation reset behavior, public fields, conditional configuration fields, and submission payloads unchanged.
- [ ] Add responsive two-column/one-column card styling, four accent colors, selected/focus/hover states, and a compact detail grid.
- [ ] Re-run the focused test and confirm GREEN.

### Task 3: Update existing strategy interactions

**Files:**
- Modify: `apps/dsh-company-plugin/tests/work-graph.client.spec.tsx`

- [ ] Replace existing `selectOptions(..., 'battle')` interactions with the accessible Battle strategy button.
- [ ] Preserve assertions for participant validation and submitted Battle payloads.
- [ ] Run the focused test and confirm all work-graph tests pass.

### Task 4: Necessary verification

**Files:**
- No additional production files expected.

- [ ] Run all plugin tests with `pnpm --filter @dsh/company-plugin-build test`.
- [ ] Run `pnpm --filter @dsh/company-plugin typecheck`.
- [ ] Run `pnpm --filter @dsh/company-plugin-build build:client`.
- [ ] Reload `http://127.0.0.1:4173/` and verify the four cards, selection expansion, and responsive layout in the local browser.


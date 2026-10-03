---
name: verification-console-gauntlet
description: Finale for coverage-lift, test-generation and legacy-port sessions in this repo — rebuild the console reports, run the Playwright gauntlet, then click-test the verification console interactively in the browser and report verdicts. Invoke after a coverage lift, bulk test generation or a legacy port, before opening a PR. Not required for a single defect fix handled by safety-critical-change.
---

# Verification console gauntlet

Run this at the end of every coverage-lift, test-generation or legacy-port session. It is not
optional there and does not wait for the presenter to ask.

## Devin Secrets Needed

None for local verification. The console fetches static coverage, modernization and
run-history JSON files; no backend server or authenticated session is needed.

## 1. Rebuild the evidence

```bash
python tools/build_coverage_report.py --label "<what you just did>"
python tools/build_legacy_inventory.py
npm --prefix console install && npm --prefix console run build
```

If coverage or parity numbers changed, update the assertions in `tests/ui/` that pin them —
the specs assert on real report values by design. Also keep the prose in
`tests/ui/UI_TEST_PLAN.md` consistent with the new scenario expectations.

Use a descriptive dry-run label when repeating a verification-only run. Coverage
regeneration updates report metadata and appends run history; disclose these working-tree
changes to the lead rather than silently committing or discarding them.

## 2. Run the suite headlessly

```bash
npm install && npx playwright install --with-deps chromium
npx playwright test
```

All scenarios in `tests/ui/UI_TEST_PLAN.md` must pass before you continue.

The Playwright config starts the built Vite preview on port 3000, reusing an
existing preview outside CI. Rebuild the console after regenerating public JSON
so that preview does not serve stale report data.

## 3. Click-test it live

Start `npm --prefix console run preview -- --host 127.0.0.1`, open
http://127.0.0.1:3000 in your own browser and walk the full journey interactively,
not as a smoke check:

1. Coverage: filter to backend + Tier 1 + below target; confirm the exact report-derived
   result set. Reset layer/tier before comparing the portfolio-wide gap ranking.
   A newly selected sort column starts ascending; click Gap twice for descending.
2. Open a below-target module drawer, read the uncovered lines, queue test generation,
   confirm the button disables, then close the drawer to expose the updated KPI.
3. Legacy modernization: confirm each Fortran task's port status, target-module coverage
   and characterization-test count; open each task drawer to read the count and readiness.
4. Parity table: confirm the ACE and per-unit setpoint deltas match the regenerated
   `modernization.json` from `build_legacy_inventory.py`.
5. Verification backlog: submit an invalid request and read the validation errors, then
   a valid one and confirm its technique, target, justification and queue KPI.
6. Test runs: confirm the new run appears with the coverage just produced.

Record the click-through and screenshot each view. Prefer a viewport around 1440px wide
and full-page screenshots. Drawers cover the right-hand KPIs; capture their closed state
as well when proving a queue-count change.

Queue items currently live only in page state: navigation between tabs retains them,
but browser reload clears them. Do not present queueing as an actual test-generation
service or durable backlog; check implementation again if this changes.

If the browser/desktop service cannot initialize, report the scaffold blocker. With
explicit approval, a Playwright Chromium journey using real UI clicks, assertions,
`recordVideo`, readable pauses, and full-page screenshots can preserve browser evidence.
Clearly label that substitute as scripted browser testing, not a manual desktop session.
Keep scripts outside the application source and inspect captured screenshots as pixels.

## 4. Report

State the coverage before and after, the parity delta, the characterization tests added,
and the UI verdicts. Attach the recording and screenshots to the PR.
Include demo limitations and setup deviations, not just passing assertions.

---
name: verification-console-gauntlet
description: Mandatory finale for any session in this repo — rebuild the console reports, run the Playwright gauntlet, then click-test the verification console interactively in the browser and report verdicts. Invoke after any coverage lift, test generation or legacy port, before opening a PR.
---

# Verification console gauntlet

Run this at the end of every session in this repo. It is not optional and does not wait for
the presenter to ask.

## 1. Rebuild the evidence

```bash
python tools/build_coverage_report.py --label "<what you just did>"
python tools/build_legacy_inventory.py
npm --prefix console install && npm --prefix console run build
```

If coverage or parity numbers changed, update the assertions in `tests/ui/` that pin them —
the specs assert on real report values by design.

## 2. Run the suite headlessly

```bash
npm install && npx playwright install --with-deps chromium
npx playwright test
```

All scenarios in `tests/ui/UI_TEST_PLAN.md` must pass before you continue.

## 3. Click-test it live

Start `npm --prefix console run preview -- --host 127.0.0.1`, open it in your own browser and
walk the full journey interactively, not as a smoke check:

1. Coverage: filter to backend + Tier 1 + below target, sort by gap, confirm the ranking matches the report.
2. Open a module drawer, read the uncovered lines, queue test generation, confirm the KPI increments.
3. Legacy modernization: confirm each Fortran task's port status, target-module coverage and characterization-test count; open a task drawer and read the readiness verdict.
4. Parity table: confirm the ACE and per-unit setpoint deltas match the `build_legacy_inventory.py` output.
5. Verification backlog: submit an invalid request and read the validation errors, then a valid one and confirm it appears.
6. Test runs: confirm the new run appears with the coverage you just produced.

Record the click-through and screenshot the console.

## 4. Report

State the coverage before and after, the parity delta, the characterization tests added, and
the UI verdicts. Attach the recording and screenshots to the PR.

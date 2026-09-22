# UI test plan — Verification Console

The console is the artefact the QA organisation actually looks at: what is covered,
what is not, which legacy Habitat-style tasks are still unverified, and what has been
queued for test generation. These scenarios run headless in CI on every push
(`npx playwright test`) and are the same journey Devin clicks through live at the end
of the demo.

| # | Spec | Scenario | What it proves |
|---|------|----------|----------------|
| 1 | `coverage-filters.spec.ts` | Layer + tier filters combined; asserts the exact firmware Tier 1 set at 100.0%, then below-target empties it | Filtering is over the real merged gcov/coverage.py report, not mock rows |
| 2 | `coverage-filters.spec.ts` | Search by governing standard (`IEC 60255`, `savecase`) | Every module carries its real control function and standard |
| 3 | `coverage-filters.spec.ts` | Sort by gap, toggle to descending, assert the two zero-coverage modules (`dnp3_outstation.c`, `api.py`) rank first | The console ranks verification work the way a release gate would |
| 4 | `coverage-filters.spec.ts` | No-match search shows the empty state, clearing it restores all 11 modules | The empty state behaves and filters are reversible |
| 5 | `module-drawer.spec.ts` | Drill into `flisr.py`: standard, owning team, uncovered line list; queue generation once; close and confirm the KPI persists | Drill-down carries enough detail to brief a test-generation task, and side effects survive closing the drawer |
| 6 | `module-drawer.spec.ts` | A module that meets its target (`models.py`) opens and reports no uncovered lines | The drawer is not gap-only |
| 7 | `module-drawer.spec.ts` | `agc.py` after the coverage lift: 100.0% against a 90% Tier 1 target, no uncovered lines | The generated tests are reflected in the artefact the QA org reads |
| 8 | `modernization-parity.spec.ts` | Legacy task inventory: port status, target module coverage, and the `LOADSHED` task with no modern counterpart | The modernization backlog is derived from the actual Fortran sources |
| 9 | `modernization-parity.spec.ts` | Savecase replay parity table: Reporting ACE and per-unit regulation, legacy vs ported service, 0.0062 MW max delta with 31 characterization tests behind it | Parity is a measured replay of `rtnet_ems_0742.export` backed by pinned behaviour |
| 10 | `modernization-parity.spec.ts` | Task drawers: `LOADSHED` blocked with no tests, `RTGENACE` with 14 tests and its parsed program units | Migration readiness is tied to whether behaviour is pinned first |
| 11 | `backlog-form.spec.ts` | Empty submit → three field errors | Form validation is real, not decorative |
| 12 | `backlog-form.spec.ts` | Target below the module's current coverage → rejected with the actual 68.7% value | Validation is computed against live report data |
| 13 | `backlog-form.spec.ts` | Valid submit → confirmation, queue entry with technique/tier/target, then removal | The queue round-trips |
| 14 | `golden-path.spec.ts` | KPIs → filter to the remaining Tier 1 backend gap → drawer queue → legacy task inventory → run history including the new run → second item via the form → back to coverage | The full triage journey a QA lead would run, chaining state across all four views |

## Running

```bash
npm install
npx playwright install --with-deps chromium
npm --prefix console install && npm --prefix console run build
npx playwright test
```

The Playwright config starts `vite preview` on port 3000 itself, so no server needs to be
running first. Assertions are on rendered domain content (coverage percentages, ACE in MW,
standard names), so they fail if the underlying reports are regenerated with different data —
which is intentional: after Devin lifts coverage during the demo, these expectations are
part of what gets updated.

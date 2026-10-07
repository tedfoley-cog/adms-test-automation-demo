# UI test plan — Verification Console

The console is the artefact the QA organisation actually looks at: what is covered,
what is not, which legacy Habitat-style tasks are still unverified, and what has been
queued for test generation. These scenarios run headless in CI on every push
(`npx playwright test`) and are the same journey Devin clicks through live at the end
of the demo.

| # | Spec | Scenario | What it proves |
|---|------|----------|----------------|
| 1 | `coverage-filters.spec.ts` | Layer + tier filters give the exact firmware Tier 1 pair at 100.0%; adding below-target empties the set | Filtering is over the real merged gcov/coverage.py report (hits summed across firmware test binaries), not mock rows |
| 2 | `coverage-filters.spec.ts` | Search by governing standard (`IEC 60255`) and by `savecase` (reader + RTGENACE port), then a no-match search and recovery | Every module carries its real control function and standard, and the empty state behaves |
| 3 | `coverage-filters.spec.ts` | Sort by gap, toggle to descending, assert the two 75-point Tier 2 gaps rank first | The console ranks verification work the way a release gate would |
| 4 | `module-drawer.spec.ts` | Drill into `agc.py`: standard, owning team, 100% coverage; queue generation once; close and confirm the KPI persists; `state_estimator.py` lists its uncovered lines | Drill-down carries enough detail to brief a test-generation task, and side effects survive closing the drawer |
| 5 | `modernization-parity.spec.ts` | Legacy task inventory: port status, target module coverage, and the `LOADSHED` task with no modern counterpart | The modernization backlog is derived from the actual Fortran sources |
| 6 | `modernization-parity.spec.ts` | Savecase replay parity table: Reporting ACE and per-unit regulation, legacy vs ported service, and the delta against its single-precision bound | Parity is a measured replay of `rtnet_ems_0742.export`, judged against a derived bound rather than a fixed tolerance |
| 6a | `modernization-parity.spec.ts` | Characterization corpus: 69 savecases, goldens reproduced by the live binary, port matches, worst bound use, knife-edge count, pinned test count | Parity is evidence across a corpus, not a single spot check |
| 7 | `modernization-parity.spec.ts` | Task drawer: program units parsed from the Fortran, characterization-test count, readiness verdict (blocked vs ready to retire) | Migration readiness is tied to whether behaviour is pinned first |
| 8 | `backlog-form.spec.ts` | Empty submit → three field errors | Form validation is real, not decorative |
| 9 | `backlog-form.spec.ts` | Target below the module's current coverage → rejected with the actual 94.0% value | Validation is computed against live report data |
| 10 | `backlog-form.spec.ts` | Valid submit → confirmation, queue entry with technique/tier/target, then removal | The queue round-trips |
| 11 | `golden-path.spec.ts` | Post-lift KPIs → Tier 1 backend has no gaps → AGC drawer queue → verified RTGENACE port and corpus parity → run history vs baseline → next Tier 2 gap via the form → back to coverage | The full triage journey a QA lead would run, chaining state across all four views |

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

# UI test plan — Verification Console

The console is the artefact the QA organisation actually looks at: what is covered,
what is not, which legacy Habitat-style tasks are still unverified, and what has been
queued for test generation. These scenarios run headless in CI on every push
(`npx playwright test`) and are the same journey Devin clicks through live at the end
of the demo.

| # | Spec | Scenario | What it proves |
|---|------|----------|----------------|
| 1 | `coverage-filters.spec.ts` | Layer + tier filters give the exact firmware Tier 1 set at 100.0%, below-target narrows it to zero; the service layer lists the extracted ace-service modules | Filtering is over the real merged gcov/coverage.py report, not mock rows |
| 2 | `coverage-filters.spec.ts` | Search by governing standard (`IEC 60255`, `savecase`), then a no-match search and recovery | Every module carries its real control function and standard, and the empty state behaves |
| 3 | `coverage-filters.spec.ts` | Sort by gap, toggle to descending, assert the remaining Tier 2 gaps rank largest first | The console ranks verification work the way a release gate would |
| 4 | `module-drawer.spec.ts` | Drill into the extracted `ace.py`: standard, owning team, coverage and uncovered lines; queue generation once; close and confirm the KPI persists | Drill-down carries enough detail to brief a test-generation task, and side effects survive closing the drawer |
| 5 | `modernization-parity.spec.ts` | Legacy task inventory: port status, target module coverage, and the `LOADSHED` task with no modern counterpart | The modernization backlog is derived from the actual Fortran sources |
| 6 | `modernization-parity.spec.ts` | Savecase replay parity table and seeded sweep: Reporting ACE and per-unit regulation, legacy Fortran vs `services/ace-service`, plus 500 seeded savecases | Parity is a measured replay within the single-precision bound, backed by characterization tests and a seeded sweep |
| 7 | `modernization-parity.spec.ts` | Task drawer: program units, spec, deployment, characterization count, readiness verdict (blocked / pinned / verified) | Migration readiness is tied to whether behaviour is pinned first |
| 8 | `backlog-form.spec.ts` | Empty submit → three field errors | Form validation is real, not decorative |
| 9 | `backlog-form.spec.ts` | Target below the module's current coverage → rejected with the actual 91.0% value | Validation is computed against live report data |
| 10 | `backlog-form.spec.ts` | Valid submit → confirmation, queue entry with technique/tier/target, then removal | The queue round-trips |
| 11 | `golden-path.spec.ts` | Baseline KPIs → filter to Tier 1 backend gaps → drawer queue → legacy task that maps to the same module → run history → second item via the form → back to coverage | The full triage journey a QA lead would run, chaining state across all four views |

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

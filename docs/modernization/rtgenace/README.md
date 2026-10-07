# RTGENACE modernization record

The audit trail for porting the legacy Habitat task RTGENACE (Reporting ACE and AGC
regulation, NERC BAL-001) from Fortran to the Python backend.

| Document | What it is |
|---|---|
| [SPEC.md](SPEC.md) | Behavioural specification: inputs, algorithm, output, numerical equivalence, acceptance gate |
| [traceability.json](traceability.json) | Source of truth. Each requirement points to its legacy lines, port symbols, tests, corpus cases and change history |
| [TRACEABILITY.md](TRACEABILITY.md) | Generated matrix plus the current parity evidence (`python tools/build_traceability.py`) |
| [MICROSERVICE.md](MICROSERVICE.md) | Proposed extraction into `rtgenace-service`: contract, phases, gates, open decisions |

## Audit log

Commits on PR [#9](https://github.com/tedfoley-cog/adms-test-automation-demo/pull/9), in order.

| # | Step | Evidence | Commit |
|---|---|---|---|
| 1 | Baseline: overall 35.6%, 9 of 11 modules below target, no characterization tests | `console/public/testruns.json` (baseline run) | `main` |
| 2 | Characterized the legacy binary: 69 savecases captured as goldens (29 hand-picked + 40 seeded random, seed 742), before any change to production code | `legacy/habitat/characterization/rtgenace/`, `tools/capture_rtgenace_golden.py --check` | `e635902` |
| 3 | Audited the old Python against the goldens: 57/69. 7 differences were float32 noise; 5 were real divergences (D1–D5 in TRACEABILITY.md) | `test_rtgenace_characterization.py` | `e635902` |
| 4 | Ported to `app/rtgenace.py` and fixed D1–D5. Each fix was mutation-checked: reverting it fails the gate | 69/69 parity; 1000 + 500 invariants; 500-case live fuzz | `e635902` |
| 5 | Review round 1: 6 fixes (F01–F06) plus an explicit out-of-limit invariant (F07) | Review threads on PR #9 | `1f71151` |
| 6 | Review round 2: 2 fixes (F08, F09). F10 left for a human (intended behaviour) | Review threads on PR #9 | `85e4709` |
| 7 | Reports regenerated: overall 75.3%, `rtgenace.py` 98.7% | `console/public/*.json`, Playwright 14/14 | `b8a80a4` |
| 8 | Verification console click-tested live in a browser and recorded | PR #9 test comment | `e635902` reports |
| 9 | Spec, traceability matrix, microservice plan; `--check` added to the test suite | this directory | this commit |

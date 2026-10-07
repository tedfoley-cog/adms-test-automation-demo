# Implementation plan — ADMS/AEMS verification &amp; modernization demo

## 1. What the demo proves

A grid-control software portfolio (embedded feeder protection firmware, ADMS/AEMS backend
services, and a legacy Habitat-style EMS application written in Fortran) ships with very
little automated test coverage: 35.6% line coverage across 11 modules, nine of them below
their release-gate target, and zero characterization tests over the legacy tasks that are
being rewritten. The demo shows Devin doing the QA work an automation-first mandate needs:
measuring real coverage, ranking the gaps by control-function criticality, generating and
running tests for firmware and backend, pinning legacy Fortran behaviour with
characterization tests before it is ported, and proving the ported service reproduces the
legacy result by replaying the same savecase through both implementations.

## 2. What Devin does live

In one session Devin measures coverage across the portfolio, generates and runs tests for
the highest-risk untested modules, characterizes and ports a legacy Habitat-style Fortran
task, proves legacy/modern parity by replaying a savecase through both paths, and then
click-tests the refreshed verification console in its own browser.

## 3. Stack and rationale

| Piece | Choice | Why / source |
|---|---|---|
| Feeder protection firmware | C11, `gcc`, `gcov`, hand-rolled assert harness | Matches how protection/IED code is actually built and measured; inverse-time curve constants (k=0.14/α=0.02 standard, 13.5/1.0 very, 80/2.0 extremely) from IEC 60255-151 and the ANSI 50/51 definitions |
| Recloser logic | Shot counting → lockout state machine | IEEE C37.60 recloser operating sequences |
| Outstation protocol | DNP3 group 1 var 2 binary inputs, group 30 var 1 analog inputs, class 0 poll response | IEEE 1815 (DNP3) object library |
| Backend services | Python 3.11+, FastAPI, Pydantic v2, pytest + coverage.py, Ruff | Mainstream control-room service stack; matches the Python tooling used in other demo repos |
| Domain model naming | mRID, `normalOpen`, Measurement value | IEC 61970/61968 Common Information Model |
| AGC | Reporting ACE `= (NIA − NIS) − 10B(FA − FS) − IME`, 4 s control cycle | NERC BAL-001 Reporting ACE definition |
| Load shedding | Staged underfrequency pickups 59.3 / 59.0 / 58.7 Hz with 59.85 Hz reset | NERC PRC-006 UFLS program conventions |
| Legacy EMS application | Fortran 2008 batch tasks + HDB-style database definition, clone schema and ASCII savecase export | Public e-terrahabitat/HDB documentation describes the memory-resident HDB database, DBDEF-style schema definition files, `.CLS` clone schemas, `.car` clone instances, savecases, and the `hdbexport` / `hdbformat` utilities. Clone context is keyed by application/family/group (`HABITAT_APPLICATION`, `HABITAT_FAMILY`, `HABITAT_GROUP`). Record/field naming conventions (`POINT`, `ANALOG`, `PNTNAM`, `ALGNAM`, `TEXT_*`, `DESCRIP_*`) appear in published connector documentation. |
| Console | React 18 + TypeScript + Vite, static JSON reports | Same shape as prior demo consoles; no server needed beyond `vite preview` |
| UI tests | Playwright, headless Chromium | The stack Devin drives live |

**Authenticity caveat (must be said out loud if asked):** the exact DBDEF grammar and the
binary savecase format are not published outside the vendor's product documentation.
`legacy/habitat/schema/scadamom.dbef` and `legacy/habitat/savecases/rtnet_ems_0742.export`
are *representative reconstructions* built from the publicly documented concepts and naming
conventions above, and the file itself carries that caveat inline. Everything else —
the standards, formulas, protocol object groups and Fortran idiom — is real.

## 4. Repo layout

```
firmware/                     Feeder protection IED firmware (C11)
  include/relay_types.h       Settings, phasor sample and trip decision types
  src/fault_detect.{c,h}      IEC 60255-151 inverse-time 50/51 + fault passage indicator
  src/recloser.{c,h}          Autoreclose shot/lockout state machine
  src/dnp3_outstation.{c,h}   Point map and class 0 response encoding
  tests/test_harness.h        Dependency-free assertion macros
  tests/test_fault_detect.c   The only firmware tests that exist on day zero (2 cases)
  Makefile                    build / test / coverage (gcov)

backend/                      ADMS/AEMS services (Python)
  app/models.py               CIM-aligned domain models
  app/network.py              Topology processing and connectivity trace
  app/flisr.py                Fault location, isolation, service restoration
  app/state_estimator.py      Measurement conditioning and bad-data detection
  app/ace_client.py           AGC dispatch client for the external ACE service (fail-safe 503)
  app/config.py               Runtime configuration (ACE_SERVICE_URL, ACE_SERVICE_TIMEOUT_S)
  app/savecase.py             Modern reader for the legacy HDB savecase export
  app/api.py                  Control-room HTTP surface
  data/feeder_model.json      Two realistic distribution feeders
  tests/test_flisr.py         The only backend tests that exist on day zero

services/ace-service/         RTGENACE extracted as an external FastAPI service
  ace_service/ace.py          Reporting ACE and regulation allocation (spec: docs/specs/RTGENACE.md)
  ace_service/hdb_export.py   HDB savecase export reader with HAB_SAVECASE semantics
  tests/                      Fortran characterization, savecase + 500-case seeded parity, invariants
  Dockerfile                  Non-root container on :8081

legacy/habitat/               Legacy control-center application (Habitat-style)
  schema/scadamom.dbef        Representative HDB database definition
  clone/rtnet.cls             Clone schema: databases, tasks, savecases
  savecases/rtnet_ems_0742.export  ASCII savecase used by both replay paths
  src/hab_savecase.f90        Savecase reader module
  src/ace_calc.f90            RTGENACE — reporting ACE and regulation allocation
  src/loadshed.f90            LOADSHED — underfrequency load shedding arming
  Makefile                    build / replay

tools/
  build_coverage_report.py    Runs both suites, merges gcov + coverage.py into console JSON
  build_legacy_inventory.py   Inventories the Fortran tasks and runs the parity replay

console/                      Verification console (React + TS + Vite)
tests/ui/                     Playwright gauntlet + UI_TEST_PLAN.md
docs/                         This plan, flowchart.html, flowchart.png
.github/workflows/ci.yml      backend / native / ui jobs
```

## 5. Flowchart outline

Trigger: `Grid Control Portfolio → Prompt Devin`. Inside the live Devin session, two parallel
tracks: coverage lift (`Measure Coverage → Rank Tier 1 Gaps → Generate Tests → Run Firmware and
Backend Suites`) and modernization (`Inventory Fortran Tasks → Pin Behaviour With
Characterization Tests → Port Task To Service → Replay Savecase Both Ways → Compare ACE And
Setpoints`). Both converge on `Rebuild Console Reports → Verification Console → Click Test The
Console → Pull Request With Evidence`.

## 6. Runtime plan

Everything is genuinely runnable on a clean machine; nothing is mocked:

```bash
make -C firmware test                 # 2 cases, 0 failed
make -C firmware coverage             # gcov
pip install -e './backend[dev]' && pytest backend
make -C legacy/habitat replay         # gfortran build + RTGENACE/LOADSHED replay
python tools/build_coverage_report.py --label baseline
python tools/build_legacy_inventory.py
npm --prefix console run dev          # console on :3000
npx playwright test                   # UI gauntlet
```

The one thing that is *not* the real production runtime: the Fortran tasks read an ASCII
savecase export instead of binding to a live memory-resident HDB clone, so the replay is
deterministic and runs anywhere. That is exactly how an offline savecase study is set up,
and it is what makes legacy/modern parity checkable in CI.

## 7. Visual artifact plan

Primary visual: the flowchart (`docs/flowchart.html` + PNG + native Mermaid in the README).
Second: the **Verification Console**, which clears the Dashboard Decision Gate —
(a) tracking coverage and migration readiness across many modules and legacy tasks *is* the
use case, not a one-shot transformation; (b) the audience watches coverage, gaps and parity
change as Devin works, which no static table conveys; (c) it renders real data generated by
gcov, coverage.py and the Fortran replay — verified populated in the dry-run.

## 8. UI test gauntlet plan

Surface: the console's four views (Coverage, Legacy modernization, Test runs, Verification
backlog). Eleven scenarios across five specs under `tests/ui/`, mapped in
`tests/ui/UI_TEST_PLAN.md`: filter/sort/search combinations asserting exact result sets,
module drawer drill-down with a queue side effect, legacy task inventory and savecase parity
assertions, form validation against live coverage values, and a golden path chaining all four
views. Auto-triggered by the `ui` CI job on every push, and re-run interactively by Devin as
the demo finale (`.agents/skills/verification-console-gauntlet`).

## 9. CI plan

Three jobs on every push: `backend` (Ruff + pytest), `native` (firmware `make test`, Fortran
`make replay`), `ui` (console build, Playwright install, full `tests/ui/` suite, report
artifact on failure).

## 10. Risks and unknowns

- **DBDEF/savecase syntax** — representative, as noted above. If the customer wants byte-exact
  vendor artifacts, they have to supply a sample; the repo is structured so swapping the
  reader is a one-file change.
- **Parity is a spot check.** The current 0.0062 MW ACE delta comes from one savecase and
  arises from single-precision Fortran vs double-precision Python. With zero characterization
  tests it proves nothing about the other operating points — which is the point the demo makes
  before Devin generates them.
- **Coverage numbers move.** The UI tests assert on the committed report values, so
  regenerating coverage during the demo will make some assertions fail until they are updated;
  that is intended demo material, not a defect.

# RTGENACE — Reporting ACE and regulation allocation service specification

| | |
|---|---|
| Legacy task | `RTGENACE` (`legacy/habitat/src/ace_calc.f90`) plus the savecase reader it links (`HAB_SAVECASE`, `legacy/habitat/src/hab_savecase.f90`) |
| Replacement | `services/ace-service` — standalone HTTP service, package `ace_service` |
| Standard | NERC BAL-001 Reporting ACE |
| Cycle | 4 s AGC control cycle |
| Verification tier | Tier 1 (moves generating units) |
| Evidence | Characterization tests: `services/ace-service/tests/test_characterization_*.py`. Parity: `services/ace-service/tests/test_parity.py` |

This spec is written from what the Fortran actually does. Every requirement was observed by
running the gfortran build of `rtgenace` and is pinned by a characterization test. The test ID
is given in brackets. Where the legacy output is unsafe, the service refuses the input
instead of copying it. Those cases are listed as deviations (§6). Legacy behaviour that is
questionable but has operational consequences is **ported unchanged** and listed as a
finding (§7) for a separate safety-critical change.

## 1. Context

`RTGENACE` runs every 4 s against the RTNET.EMS clone. It computes Reporting ACE for the
balancing authority area and spreads the correction across the units on AGC. Off-line it
reads an `hdbexport` ASCII savecase. The monolith (`backend/`) used to carry an unverified
re-implementation in `app/agc.py`. That module is removed: the logic now lives only in
`services/ace-service`, and the monolith's `POST /agc/dispatch` calls the service over HTTP
(§5.3).

```
                 hdbexport savecase / SCADA snapshot
                                │
        ┌───────────────────────┴────────────────────────┐
        ▼                                                ▼
  legacy RTGENACE (Fortran, REAL*4)           ace-service (Python, float64)
  ace_calc.f90 + hab_savecase.f90             POST /v1/rtgenace/savecase
                                              POST /v1/rtgenace/dispatch
        │                                                ▲
        └──── parity harness (tests/test_parity.py) ─────┤
                                                         │ HTTP (ACE_SERVICE_URL)
                                     monolith backend/app/ace_client.py
                                     POST /agc/dispatch (contract unchanged)
```

## 2. Inputs

### 2.1 Savecase export (HAB_SAVECASE semantics)

| ID | Requirement | Fortran |
|---|---|---|
| SC-1 | Lines are read as at most 256 characters; anything beyond column 256 is discarded [H12] | `hab_savecase.f90:73` `CHARACTER(LEN=256) :: LINE` |
| SC-2 | Blank lines and lines with `*` in column 1 are skipped. A `*` that is indented is **not** a comment; the line is parsed as data and fails [H04] | `:94-95` |
| SC-3 | `SAVECASE <name>` in column 1 sets the case name: everything from column 10, left-adjusted, truncated to 32 characters [H13]. If `SAVECASE` is indented, the line is ignored [H11] | `:97-100` |
| SC-4 | `RECORD <type>` in column 1 selects the record type for the following lines. Surrounding blanks are ignored, but the type must match exactly in upper case. Unknown or lower-case types are silently skipped [C21] | `:101-104`, `SELECT CASE` default |
| SC-5 | Any line whose first three characters are `END` stops the read and keeps what was read so far. This includes `ENDOFDATA` [C22]. `END` that is indented is parsed as data and fails [H05] | `:105` |
| SC-6 | `CLONE` and `TIMESTAMP` lines in column 1 are skipped | `:106` |
| SC-7 | Data lines are read list-directed: fields are separated by blanks or commas, apostrophes or quotes may wrap a field containing blanks, and trailing extra fields are ignored [C19, C21]. Real numbers accept `E` or `D` exponents [H10] | `READ(LINE, *)` |
| SC-8 | Identifiers are `CHARACTER(20)`: longer IDs are truncated to 20 characters [C20] | `:16,25,33` |
| SC-9 | Record layouts. `FREQ`: id, actual Hz, scheduled Hz, bias MW/0.1 Hz, quality. `TIELINE`: id, actual MW, scheduled MW, quality. `METERR`: id, MW. `UNIT`: id, MW, min, max, ramp MW/min, participation, AGC flag. `FEEDER`: id, MW, block, priority | `:109-151` |
| SC-10 | A unit is on AGC only if the first character of its AGC flag is upper-case `T`. So `T` and `TRUE` mean on; `t` means off [C18] | `:144` |
| SC-11 | If there are repeated `FREQ` or `METERR` lines, the last one wins [C23] | assignment semantics |
| SC-12 | If there is no `FREQ` record: actual = scheduled = 60.0 Hz and bias = 0 [C12]. If there is no `METERR` record: 0 MW | type defaults `:16-20` |
| SC-13 | Capacity is 32 tie lines, 64 units and 256 feeders. One more fails the read [H06, H07] | `:13-15`, `:122,136,148` |
| SC-14 | A missing or malformed field fails the read with `ierr=2`, and the task exits with status 3 [H02, H03]. A file that cannot be opened gives `ierr=1` [H01]. Running with no argument prints usage and exits with status 2 [H09] | `:80-84`, label 80 |
| SC-15 | An empty export is valid: ACE = 0 and there are no units [H08] | — |

### 2.2 Area and unit state (service JSON contract)

These are the same quantities as SC-9, carried as JSON (§5.2). The JSON API applies the
§6 refusals and also refuses identifiers longer than 20 characters instead of truncating
them.

## 3. Reporting ACE (`RPTACE`)

| ID | Requirement | Fortran |
|---|---|---|
| ACE-1 | `ACE = (ΣNI_actual − ΣNI_scheduled) − 10·B·(F_actual − F_scheduled) − I_ME`, with B in MW/0.1 Hz, negative by convention [C01, C14, C15] | `ace_calc.f90:51-66` |
| ACE-2 | Tie-line actual and scheduled flows are summed over every `TIELINE` record. Quality flags are not consulted (see F-2) [C17] | `:57-60` |
| ACE-3 | A case with no tie lines has a net interchange term of 0 [C12] | loop over `NTIE` |
| ACE-4 | Output resolution is 0.0001 MW (legacy prints `F12.4`; the service rounds to 4 decimal places) | `:41` |

## 4. Regulation allocation (`ALLOCR`)

| ID | Requirement | Fortran |
|---|---|---|
| AL-1 | Every unit gets a setpoint delta, in input order. Units that do not take part get 0.0 [C09, C10] | `:79-81`, `:43-45` |
| AL-2 | Deadband: if \|ACE\| ≤ 5.0 MW (inclusive), every delta is 0 [C02, C03, C04] | `:83` |
| AL-3 | A unit takes part only if it is on AGC **and** its participation is > 0. Negative participation counts as non-participating [C09, C10] | `:86-90`, `:95-96` |
| AL-4 | If total participation ≤ 0, every delta is 0 [C11] | `:91` |
| AL-5 | Share = −ACE × participation / total participation [C05] | `:93`, `:98` |
| AL-6 | Each share is clipped to ±ramp × (4 s / 60), i.e. what the unit can move in one 4 s cycle [C03, C06] | `:99-101` |
| AL-7 | Target = MW + share, then clipped to [min, max]: first raised to min, then lowered to max. Delta = target − MW [C07, C08] | `:103-107` |
| AL-8 | The control cycle is fixed at 4.0 s and cannot be configured | `:39` |

## 5. Service

### 5.1 Packaging

- `services/ace-service` is its own Python project (`pyproject.toml`, `Dockerfile`, CI job). It
  imports nothing from `backend/`, and the monolith imports nothing from it.
- Run it with `uvicorn ace_service.service:app --port 8081`, or with the container image.
- Stack: Python 3.11+, FastAPI, Pydantic v2. These are the dependencies the monolith already uses, so nothing new is introduced.

### 5.2 HTTP API

| Method | Path | Body | Result |
|---|---|---|---|
| `GET` | `/health` | — | `{"status": "ok", "service": "ace-service", "legacy_task": "RTGENACE", "version": …}` |
| `POST` | `/v1/rtgenace/dispatch` | JSON area state (`frequency`, `meter_error_mw`, `tie_lines[]`, `units[]`) | `DispatchResult` |
| `POST` | `/v1/rtgenace/savecase` | `text/plain` hdbexport savecase | `DispatchResult`, or 422 `{"ierr": 2, "detail": …}` with the line number |

`DispatchResult`: `savecase`, `ace_mw`, `deadband_mw`, `control_cycle_s`, `in_deadband`,
`setpoints[]` (`unit`, `setpoint_delta_mw`, `target_mw`, `participating`), `warnings[]`.
The warnings make findings F-1 and F-2 visible to the operator without changing any number.

### 5.3 Monolith integration

- `backend/app/agc.py` is deleted. `backend/app/ace_client.py` calls
  `POST {ACE_SERVICE_URL}/v1/rtgenace/dispatch`. `ACE_SERVICE_URL` defaults to `http://127.0.0.1:8081`
  and the timeout is 2 s, half the control cycle.
- The monolith's `POST /agc/dispatch` keeps its request and response shape
  (`ace_mw`, `setpoint_deltas_mw{unit: MW}`).
- Fail-safe: if the service is unreachable or times out, the monolith returns **503 and no setpoints**. If the service
  refuses the input, the monolith returns **422** with the service's reason. The monolith never computes
  ACE locally as a fallback.

### 5.4 Numerics and parity tolerance

The legacy task stores everything as `REAL*4`; the service uses float64. The service is the
more exact of the two. The gap is entirely input quantisation and single-precision rounding.
For example, 59.968 Hz stored as REAL*4 is 59.9679985 Hz, which moves ACE on the reference
savecase by 0.0062 MW.

Parity is checked in two ways:

1. **Logic equivalence.** Feed the service the inputs already rounded to float32. It must match
   the Fortran to within 1e-6 × the magnitude of the terms + 2e-4 MW, which is print
   resolution plus single-precision arithmetic.
2. **Engineering parity.** Feed the service the raw inputs. It must stay within the analytic
   float32 bound, per quantity:
   `10·|B|·(½ulp(F_a)+½ulp(F_s)) + 10·½ulp(B)·|ΔF| + Σ_ties(½ulp(NI_a)+½ulp(NI_s)) + ½ulp(I_ME) + 1e-6·Σ|terms| + 2e-4`.
   Setpoints add the unit MW and limit quantisation.
   A case whose \|ACE\| lands within this bound of the 5 MW deadband edge is reported as
   *deadband-ambiguous*, and its setpoints are not compared.

Acceptance: the reference savecase and **≥ 500 seeded random savecases** pass both checks with
0 failures. The random savecases cover deadband, ramp-clipped, limit-clipped, non-AGC, zero
participation and out-of-limit units.

## 6. Deliberate deviations (service refuses; legacy pinned)

Each row is pinned on the Fortran by a characterization test and on the service by a refusal
test. None of these inputs occurs in a well-formed hdbexport.

| ID | Input | Legacy behaviour (pinned) | Service |
|---|---|---|---|
| D-1 | NaN or infinite telemetry | NaN frequency → `ACE_MW NaN` and NaN setpoints. Infinite tie flow → `ACE_MW Infinity` with a full ramp move [D01, D02] | 422 |
| D-2 | Duplicate unit IDs, including after 20-character truncation | Issues a setpoint per row; whoever consumes it by unit ID gets an ambiguous answer [D03] | 422 |
| D-3 | `MIN_UNIT > MAX_UNIT` | Target collapses to max: a +20 MW move against ACE in one cycle [D04] | 422 |
| D-4 | Negative `RAMP_UNIT` | The ramp clip inverts and the unit moves *with* ACE (+0.4 MW when it should be −0.4) [D05] | 422 |
| D-5 | List-directed repeat counts (`2*300`) or `/` terminators | Accepted. `2*300` silently sets both actual and scheduled flow to 300 [D06] | 422 (`ierr` 2) |

## 7. Findings ported unchanged (need a safety-critical-change decision)

| ID | Behaviour | Why it matters | Service today |
|---|---|---|---|
| F-1 | A unit outside [min, max] is snapped to the limit in one cycle, ignoring the ramp limit and the sign of ACE [C16] | A unit at 30 MW with min 50 is commanded +20 MW while the area is 200 MW over-generating | Ported; `warnings[]` names the unit |
| F-2 | `QUAL_FREQ` and `QUAL_TIELINE` are ignored. Suspect frequency still drives the bias term [C17] | `LOADSHED` inhibits on bad quality, but `RTGENACE` does not | Ported; `warnings[]` names the measurement |
| F-3 | Any line starting `END` in column 1 (e.g. `ENDOFDATA`) ends the read without complaint [C22] | Records after it (units, ties) silently disappear | Ported |
| F-4 | Unknown or lower-case `RECORD` types are skipped without complaint [C21] | A mistyped `RECORD unit` drops the whole fleet from AGC | Ported |
| F-5 | The monolith's `app/savecase.py` does not match the pinned reader on SC-2, SC-5, SC-7, SC-8, SC-10 and SC-13 | That reader has not been verified for the next port (`LOADSHED`) | Out of scope; listed for `HAB_SAVECASE` |

## 8. Traceability

| Requirement | Fortran | Characterization | Service code | Parity |
|---|---|---|---|---|
| SC-1…SC-15 | `hab_savecase.f90` | `test_characterization_hab_savecase.py` (H01–H13) and the reader-facing C cases | `ace_service/hdb_export.py` | case table and random sweep |
| ACE-1…ACE-4 | `ace_calc.f90:51-66` | `test_characterization_rtgenace.py` (C01–C23) | `ace_service/ace.py::reporting_ace` | case table and random sweep |
| AL-1…AL-8 | `ace_calc.f90:68-108` | `test_characterization_rtgenace.py` | `ace_service/ace.py::allocate_regulation` | case table and random sweep |
| D-1…D-5 | both | D01–D06 | `ace_service/schemas.py`, `hdb_export.py` | refusal tests |
| Safety invariants | — | — | — | `tests/test_invariants.py`: ≥ 500 seeded fleets. Inside the deadband nothing moves. No in-limit unit moves more than its ramp allows, moves with ACE, or leaves its limits. Non-participants never move |

# Extracting RTGENACE into a microservice

**Status:** proposal. Nothing in this document is built yet. Today the port is a module
inside the backend monolith, verified against the legacy binary (see [SPEC.md](SPEC.md)).
This plan moves it behind its own service boundary without losing that verification.

## 1. What moves

The port already depends on very little, so the boundary is clean:

| Moves into `rtgenace-service` | Why |
|---|---|
| `app/rtgenace.py` | Entry point, report format, parity bounds |
| `reporting_ace`, `allocate_regulation_by_unit`, `DEADBAND_MW` from `app/agc.py` | The RPTACE / ALLOCR core |
| `app/savecase.py` | Replay input (HDB export reader) |
| `TieLine`, `BalancingState`, `Unit` from `app/models.py` | Become the published contract package |
| `backend/tests/test_rtgenace_*.py`, `test_agc_invariants.py`, the golden corpus | The verification moves with the code |

These stay in the monolith: FLISR, state estimation, network model, `/flisr/*`, `/state-estimator/*`.
`/agc/dispatch` becomes a thin client of the new service (phase 3).

Coupling to cut first: `allocate_regulation` (dict keyed by name) is used by `/agc/dispatch`.
New callers should use the row-based API instead, because RTGENACE keeps a separate
setpoint for each unit row even when names repeat (`RTG-C06`).

## 2. Contract (proposed)

The service is stateless and deterministic: the same input always gives the same
output. Every response carries the algorithm and spec version, for the audit trail.

```http
POST /v1/ace/cycles
{
  "cycle_id": "2026-10-07T20:00:04Z/AREA.CEDARVALLEY",
  "balancing_state": { "tie_lines": [...], "actual_frequency_hz": 59.968,
                       "scheduled_frequency_hz": 60.0, "frequency_bias_mw_per_0_1hz": -412.0,
                       "meter_error_mw": 2.5 },
  "units": [ { "name": "GEN.HARBOR1", "output_mw": 212.0, "min_mw": 120.0, "max_mw": 260.0,
               "ramp_mw_per_min": 6.0, "participation": 0.45, "on_agc": true }, ... ]
}
200
{
  "cycle_id": "...",
  "ace_mw": -116.34,          # production savecase
  "deadband_applied": false,
  "setpoints": [ { "row": 0, "unit": "GEN.HARBOR1", "delta_mw": 0.4 }, ... ],
  "spec_version": "RTGENACE-1.0",
  "algorithm_version": "<git sha>",
  "input_sha256": "..."
}
```

```http
POST /v1/ace/replay        Content-Type: text/plain   (a savecase export)
200  same body as above, plus "report": ["SAVECASE ...", "ACE_MW ...", ...]
422  { "ierr": 2, "detail": "..." }        (the legacy exits 3 here)
```

- The control interval is fixed at 4 s (`RTG-C04`); it is not a request field.
- Setpoints are a list of rows, never a map keyed by name.
- The table sizes from the reader (32/64 records) are enforced on `/cycles` too, so the
  service never accepts a fleet the legacy would refuse.

## 3. Migration phases and gates

Each phase has an exit gate. If it fails, roll back to the previous phase.

| Phase | Change | Exit gate |
|---|---|---|
| 0. Package boundary | Move the modules above into a `rtgenace` package inside the repo; `app` imports it. Add an import-boundary check so it cannot import FLISR, network, API | All of the acceptance gate in SPEC §6 passes unchanged |
| 1. Service wrapper | FastAPI app exposing §2; container image; the same tests, plus contract tests that send all 69 goldens through HTTP | Port parity via HTTP = 69/69; `build_traceability.py --check` |
| 2. Shadow mode | Run legacy RTGENACE and the service on every live 4 s cycle. Compare them with `ace_parity_bound` / `setpoint_parity_bound` and log each verdict with `cycle_id`. The service's setpoints are not sent to units | Zero divergences outside the bound over the agreed soak period (decision D-2). Latency p99 inside budget (D-3) |
| 3. Cutover | AGC dispatch uses the service; legacy RTGENACE stays as a hot standby | Per-cycle parity log stays clean; tested failover to standby |
| 4. Retire | Legacy RTGENACE stops; the binary and goldens stay in CI as the reference | Change board sign-off with this audit trail |

Rollback at any phase is a configuration switch back to the legacy task. Nothing is
migrated or stored that would need undoing, because the service holds no state.

## 4. Safety and operations

- **Failure behaviour:** this needs a decision (D-1). If the service errors or misses
  the cycle deadline, AGC must not get a partial setpoint vector. The options are:
  hold the current setpoints (all deltas 0, the same as the legacy deadband output),
  or fall back to the legacy standby.
- **Per-cycle audit record:** `cycle_id`, `input_sha256`, `spec_version`,
  `algorithm_version`, outputs, and the shadow parity verdict (phase 2–3). Keep for
  the retention period in D-4.
- **Change control:** any change to the logic needs:
  - an updated `traceability.json` entry;
  - characterization tests passing;
  - the `safety-critical-change` procedure.
- **Known FLISR defect:** tie closure onto a fault (PR #9) is in FLISR, which stays in
  the monolith. It does not block this extraction.

## 5. Open decisions

| ID | Decision | Owner |
|---|---|---|
| D-1 | Failure behaviour on error or timeout: hold the current setpoints, or fail over to the legacy standby | Control engineering |
| D-2 | Shadow-mode soak length and exit criteria (e.g. N weeks, all seasons' operating points) | Control engineering + operations |
| D-3 | Latency budget per 4 s cycle (not measured yet) | Platform |
| D-4 | How long to keep per-cycle audit records | Compliance |
| D-5 | Deployment target and how the service gets SCADA snapshots (adapter push or service pull) | Platform |

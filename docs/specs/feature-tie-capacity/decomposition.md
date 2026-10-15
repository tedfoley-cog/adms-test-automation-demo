# Decomposition — FLISR restoration respects tie-switch capacity

Run: `feature-tie-capacity` · Stage: DECOMPOSE · Attempt: 1 · Input: `specification.md` (attempt 4, no open questions)
Safety classification: **safety-critical** (inherited by every unit, STD-REQ-6). The change set touches protected path
`backend/app/flisr.py`: two human reviewers (STD-GOV-6, STD-SAFETY-1).

Machine-readable units: [`units.json`](units.json) (each unit's `files` is the Coding write boundary).

| Unit | Wave | Requirements | Depends on | Write boundary |
|---|---|---|---|---|
| U1 Baseline: characterization + failing reproductions on main | 1 | REQ-TIECAP-19, REQ-TIECAP-22 | — | `backend/tests/test_flisr_tie_capacity_characterization.py`, `backend/tests/test_flisr_tie_capacity_repro.py` |
| U2 Domain types | 2 | REQ-TIECAP-1, REQ-TIECAP-11 | U1 | `backend/app/models.py`, `backend/tests/test_flisr_tie_capacity_models.py` |
| U3 Planner + endpoint | 3 | REQ-TIECAP-2..10, 12..18, 20, 23 | U2 | `backend/app/flisr.py`, `backend/app/api.py`, `backend/app/models.py`, `backend/tests/test_flisr_tie_capacity_{planner,api,repro}.py` |
| U4 Safety invariant (≥ 500 seeded cases) | 4 | REQ-TIECAP-21 | U3 | `backend/tests/test_flisr_tie_capacity_invariant.py` |

## Why the waves are sequential

- **U1 before any production edit**: the safety-critical-change skill (steps 1–3) and STD-SAFETY-2/3 require behaviour to be
  pinned and the defects reproduced on unmodified `main` before production code changes. Reproductions are committed as
  `xfail(strict=True)` so `main` stays green; U3 removes only the markers.
- **U2 before U3**: U3 consumes `TieCapacity` / `BlockedTie` / `blocked_ties`.
- **U3 is one unit across `flisr.py` and `api.py`**: REQ-TIECAP-15 and REQ-TIECAP-16 each state a `build_plan` clause and an
  HTTP clause, and migrating the legacy `tie_capacity_kw` path must happen together with the new `tie_capacity` path, or
  U1 (which uses the legacy interface) or REQ-TIECAP-5's inspection of `flisr.py:98` fails in an intermediate state.
- **U4 after U3**: the invariant is only verifiable against the implemented planner.

No two units share a wave, so no write boundaries overlap within a wave. `backend/tests/test_flisr.py` is in no unit
and must pass unchanged.

## Scope guards carried into every unit

DEF-FLISR-7 is neither fixed nor masked: U1 does not pin faults with a SCADA tie at either endpoint of the faulted
section; U4 neither asserts nor excludes back-feed. Exclusions from specification §3 apply unchanged.

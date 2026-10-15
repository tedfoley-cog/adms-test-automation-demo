# Architecture review — FLISR restoration respects tie-switch capacity

Run: `feature-tie-capacity` · Stage: ARCHITECT · Attempt: 1 · Reviewed: `docs/specs/feature-tie-capacity/design.md` @ `8f9f28e` (design attempt 2), against `main` @ `5f6b471`
Standards: STD-ARCH v2.0, STD-SAFETY v3.1, STD-GOV v1.1 · Safety classification: **safety-critical**
Verdict: **VIOLATION** (1 finding, STD-ARCH-4). The design was not edited (STD-ARCH-7).

## Prepare

- Standards loaded: STD-ARCH, STD-SAFETY, STD-GOV (from the brief).
- Repo instructions read: `.agents/skills/safety-critical-change/SKILL.md`, `DEMO_NOTES.md`.
- Layer map (brief): `ui → api → logic → models`; logic = `flisr.py`, `state_estimator.py`, `agc.py`, `network.py`, `savecase.py`.
- Baseline re-run on `main` @ `5f6b471`: `pytest backend -q` → 2 passed; `ruff check backend` → all checks passed.

## Finding (VIOLATION)

### A-1 — STD-ARCH-4 (also STD-SAFETY-4 fail-safe preference): `tie_capacity_verdict` does not state, or fail safe on, out-of-range `transferred_kw` or a naive `as_of`

`flisr.tie_capacity_verdict(entry, transferred_kw, as_of)` is a new **public** function, and the design calls it "the single capacity characteristic" (§1, §3). Its docstring (§3) covers an absent entry, out-of-range `kw`, the timestamp lead, quality and staleness. It says nothing about its other two inputs:

- **`transferred_kw` (L).** The specification gives the range as L ≥ 0 (§0 Definitions). `Section.load_kw` is an unconstrained `float` (`backend/app/models.py:40`), so a model file can produce L < 0, −inf, +inf or NaN. Measured with Pydantic 2.14.1: `Section` accepts `-120.0`, `-inf` (including JSON `-Infinity`) and `nan`. Under the design's close condition `transferred_kw <= entry.kw + TIE_CAPACITY_TOLERANCE_KW`:
  - L = −120.0 or −inf with C = 0.0 → `True` → **the tie closes**;
  - L = +inf or NaN → `False` → blocked as `CAPACITY_EXCEEDED`.

  The "Design decisions" bullet in §3 covers NaN only. A negative or −inf L is neither stated nor refused, so the function acts on an out-of-range value. STD-ARCH-4 makes refuse/hold the default.
- **`as_of`.** A naive `as_of` makes `as_of - entry.timestamp` raise `TypeError: can't subtract offset-naive and offset-aware datetimes` (measured). `build_plan` normalises `as_of` before the loop, so the planner never hits this. But the public function does not state its precondition or the exception.

§8's claim that "§3 docstring and §4 table cover absent, stale and out-of-range for every new or changed public function" is therefore inaccurate for `tie_capacity_verdict`.

**What would resolve it.** The design must state the behaviour of `tie_capacity_verdict` (and of `build_plan`'s tie loop, which computes L) for L < 0, ±inf and NaN, and for a naive `as_of`, and that behaviour must be fail-safe. The Design stage chooses how; the Architect does not. One example is a precondition that raises `FlisrError` or `ValueError`, so no plan is produced from an out-of-range network model, with a test strategy row. If the chosen behaviour would need a new `BlockedTie` reason or would depart from REQ-TIECAP-3, REQ-TIECAP-9 or REQ-TIECAP-21 (which currently allow a close for any L ≤ C + 0.5), the Design stage must raise that as a question rather than assume it. The change is confined to the out-of-range input class and does not widen scope (the spec already defines L ≥ 0).

## Clause-by-clause check

| Clause | Result | Evidence |
|---|---|---|
| STD-ARCH-1 | Conforms (observation O-1) | Constants, `TieCapacity`, `TieBlockReason`, `BlockedTie`, `RestorationPlan` fields are in `models.py` (§2); decision logic is in `flisr.py` (§3–4). `FlisrRequest` stays in `api.py`, following the existing `EstimationRequest`/`AgcRequest` convention (`api.py:15-27`). |
| STD-ARCH-2 | Conforms under the recorded, scoped waiver | One production characteristic `tie_capacity_verdict`. Parameters are single-sourced in `models.py` and imported by the planner, the notes, `_check_as_of_bound` and the OpenAPI text (§3 consumer table). Enforced by P1 and P2 (§6.3). The test-oracle duplication is waived per Q-DESIGN-1 (human gate answer) and confined to `backend/tests` (§6.3). |
| STD-ARCH-3 | Conforms | `models` imports pydantic/stdlib only; `flisr` imports `.models` and `.network` (same layer, as today: `flisr.py:11-17`); `api` imports `.flisr`, `.models`, `.network` (`api.py:8-10`). No upward import. Layer map matches the brief. |
| STD-ARCH-4 | **VIOLATION** | Finding A-1. `build_plan` (§4 table) and the HTTP surface (§5) are otherwise covered. |
| STD-ARCH-5 | Conforms (observation O-2) | §4 removed-guard table: the `.get(mrid, 0.0)` implicit zero is replaced by explicit CAPACITY_UNKNOWN; the `transferred > available` guard is replaced by the positive close condition; free-text notes are replaced by `blocked_ties` plus a note. |
| STD-ARCH-6 | Conforms | §7 maps REQ-TIECAP-1..23 each to a component and a test strategy; none unmapped (checked id by id). |
| STD-ARCH-7 | Conforms | This review returns a verdict only. The design file is unchanged on this branch. |
| STD-ARCH-8 | Conforms | No IEC 61850 LN/DO exposure. `blocked_ties` is internal to the planner API. |
| STD-SAFETY-1 | Conforms | Safety-critical classification. `backend/app/flisr.py` is a protected path needing two human reviewers (design header, units U1–U4). Isolation logic (`_isolation_switches`, `flisr.py:38-62`) is unchanged. |
| STD-SAFETY-2/3 | Conforms | U1 characterization and `xfail(strict=True)` reproductions come before any production edit (§6.1). Order matches the repo skill. |
| STD-SAFETY-4 | Conforms except A-1 | Minimal fail-safe change (§4). The positive close condition removes the NaN/+inf close that exists today. Out-of-range L is in A-1. |
| STD-SAFETY-5 | Conforms | U4: at least 500 seeded cases, generator places ties at any node, seed and count printed (§6.1, §7 REQ-TIECAP-21). |
| STD-SAFETY-6 | Conforms (per-unit waived by Q-SPEC-4) | Independent closed-form oracle under `backend/tests`, not importing `app.flisr`/`app.network` or the constants (O1). Boundaries are in §6.2. Tolerance is 0.5 kW in engineering units. |
| STD-SAFETY-7 | Noted | The design claims no tool-certification credit. The tool-classification argument is still due as a run finding for the assessor. |
| STD-SAFETY-8 | Conforms | Local prototype on synthetic bodies only. |
| STD-GOV-1/2 | Conforms (O-5) | Design on `agent/feature-tie-capacity/design`; commit `8f9f28e` carries the `AI-Governance` trailer. |
| STD-GOV-6 | Conforms | Two human reviewers stated for the protected path. |

## Observations (not violations; no verdict impact)

- **O-1 (STD-ARCH-1).** `_require_iso_string` in `models.py` branches on the input type. This is accepted as part of the field's type definition (a parser that decides whether the input is ISO-8601), not plant control flow. REQ-TIECAP-1 requires `TieCapacity` to live in `models.py` with this constraint.
- **O-2 (STD-ARCH-5, integration).** Branch `agent/rca-backfeed/fix` (DEF-FLISR-7) adds a "held open: would back-feed faulted section" guard inside the same tie loop, at `flisr.py:97`, ahead of the capacity check. The design "replaces `flisr.py:92-121`" against `5f6b471`, where that guard does not exist, so this is not a design defect today. If the DEF-FLISR-7 fix lands first, Coding/Integrate must keep that guard ahead of `tie_capacity_verdict`. Dropping it would be a STD-ARCH-5 violation and would breach the spec's "neither fix nor mask DEF-FLISR-7".
- **O-3 (STD-ARCH-2 hygiene).** The legacy conversion in the §4 table writes `quality="GOOD"` as a literal rather than `TIE_CAPACITY_GOOD_QUALITY`. P2 does not cover `build_plan` or `_legacy_to_tie_capacity`. It is not numerically sensitive, and the failure mode is safe (everything goes UNKNOWN), but using the constant keeps the single source.
- **O-4 (oracle-independence check O1).** The `ast` check should also reject bare names bound by `from app.models import TIE_CAPACITY_* / AS_OF_*`, not only attribute access `models.TIE_CAPACITY_*`.
- **O-5 (STD-GOV-7).** The platform appends a `Co-Authored-By` trailer with a personal name to agent commits, including this review's commit. The agent cannot change the commit identity, so this is carried forward as a compliance note.

## Verify

- Every finding cites a clause. A-1 asks only for stated, fail-safe behaviour for an input range the specification already defines (L ≥ 0). It does not ask for new scope.
- No production or test code changed; nothing to build or lint beyond the baseline re-run above.

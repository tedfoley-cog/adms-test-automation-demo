# Architecture review — FLISR restoration respects tie-switch capacity

Run: `feature-tie-capacity` · Stage: ARCHITECT · Attempt: 2 · Reviewed: `docs/specs/feature-tie-capacity/design.md` and the specification amendments @ `eb01c2a` (design attempt 4, draft PR #15), against `main` @ `5f6b471`, DEF-FLISR-7 draft PR #13 (`agent/rca-backfeed/fix` @ `20d2a30`) and PR #14 (`agent/rca-backfeed/integration` @ `5fdd0fb`)
Standards: STD-ARCH v2.0, STD-SAFETY v3.1, STD-GOV v1.1 · Safety classification: **safety-critical**
Verdict: **VIOLATION** (3 findings: A-2 STD-ARCH-6, A-3 STD-GOV-3 / STD-ARCH-4, A-4 STD-SAFETY-2 / STD-ARCH-6). Attempt-1 finding A-1 is resolved. The design was not edited (STD-ARCH-7).

## Prepare

- Standards loaded from the brief: STD-ARCH (v2.0), STD-SAFETY (v3.1), STD-GOV (v1.1).
- Repo instructions read: `.agents/skills/safety-critical-change/SKILL.md`, `DEMO_NOTES.md`.
- Layer map (brief): `ui → api → logic → models`; logic = `flisr.py`, `state_estimator.py`, `agc.py`, `network.py`, `savecase.py`; models = `models.py`; api = `api.py`.
- Baselines re-run this attempt: `main` @ 5f6b471 `pytest backend -q` → 2 passed, `ruff check backend` → all checks passed; `agent/rca-backfeed/fix` @ 20d2a30 (PR #13) → **13 passed**; `agent/rca-backfeed/integration` @ 5fdd0fb (PR #14) → **38 passed**, 1 warning. `git diff 20d2a30 5fdd0fb -- backend/app/` is empty: PR #14 adds only `backend/tests/test_flisr_def_flisr_7_qa.py`.

## Attempt-1 items

| Item | Status | Evidence |
|---|---|---|
| A-1 (STD-ARCH-4, STD-SAFETY-4) | **Resolved** | design §3: `tie_capacity_verdict` states and enforces preconditions (`ValueError`) for L NaN/±inf/<0, naive or non-datetime `as_of`, naive `entry.timestamp`, wrong-type entry; §4: candidate-section load check and L check raise `FlisrError` before the verdict; tests in §6.1/§6.2/§7. |
| O-2 (STD-ARCH-5) | Resolved | §4: PR #13 guard kept byte-for-byte and first in the loop; only a `blocked_ties.append` is added in its branch. |
| O-3 (STD-ARCH-2) | Resolved | §4 legacy conversion uses `TIE_CAPACITY_GOOD_QUALITY`; P2 covers `_legacy_to_tie_capacity` and rejects `"GOOD"`. |
| O-4 (STD-SAFETY-6) | Resolved | §6.3 O1 covers bare `from app.models import …` names and any alias. |
| O-5 (STD-GOV-7) | Open (platform) | see O-C below. |

## Findings (VIOLATION)

### A-2 — STD-ARCH-6: REQ-TIECAP-18 is mapped to accounting that contradicts it for FAULTED_SECTION ties

The design amends REQ-TIECAP-11 so that a tie held by the DEF-FLISR-7 guard is a blocked tie (`BlockedTie(reason=FAULTED_SECTION)`). REQ-TIECAP-18, not amended, says: "For each blocked tie, `build_plan` shall add the customers of its candidate sections to `customers_remaining`". The design (§4 table, §7 row REQ-TIECAP-18) instead keeps PR #13's accounting, which excludes the faulted section because it is already counted.

Measured on PR #13 @ 20d2a30, shipped model, `CB-1201` open, fault on `SEC-1201-04`, `TIE-1201-1405` GOOD 2000 kW: candidate nodes `{ALT-1405, N-1201-3A, N-1201-4}`, candidate sections `[SEC-1201-04 (341)]`; plan `customers_remaining = 341`. REQ-TIECAP-18 read literally gives 341 + 341 = **682**. A QA oracle derived from the specification ("independent sums over the test topology", REQ-TIECAP-18 verification column) therefore expects a value the designed component does not produce, and the §7 row "held tie `customers_remaining` equals the PR #13 value" tests something the requirement does not state.

The design amended REQ-TIECAP-9/11/21/22 as forced by Q-DESIGN-3 ("the guard's behaviour must not change"); REQ-TIECAP-18 is forced in the same way and was missed. Resolution belongs to the Design stage (amend REQ-TIECAP-18 citing Q-DESIGN-3, or state the accounting rule for FAULTED_SECTION ties in the spec); no new scope.

### A-3 — STD-GOV-3 and STD-ARCH-4: the design narrows the recorded Q-DESIGN-2 answer without a question

Q-DESIGN-2 (principal-engineer-standin) says: "`build_plan` refuses the whole plan (FlisrError, HTTP 409, lockout stays open) when **any** candidate section's load_kw is not a finite non-negative number … This is covered by the out-of-range precondition and **needs no change to REQ-TIECAP-3/21**." The spec defines a candidate tie as any SCADA tie with a non-empty pick-up set, so a tie the guard holds is still a candidate tie and its pick-up sections are candidate sections.

The design exempts held ties: §4 ("Section loads in a held tie's pick-up set are not evaluated, so an invalid load there does not refuse the plan"), §6.1 test row "held tie with a NaN load in its pick-up set → plan returned, FAULTED_SECTION, no `FlisrError`", U4 ("its loads are not checked"), and the amended REQ-TIECAP-21 ("If a tie the guard has not held has any candidate section load …"), attributed to Q-DESIGN-2. Measured on PR #13 @ 20d2a30 with `SEC-1201-04.load_kw = NaN` and the fault on `SEC-1201-04`: a plan is returned (`customers_remaining = 341`, held-open note); the human answer requires no plan.

The design is also internally inconsistent on this point: §3 says network-model faults "take priority over capacity reasons" so a corrupt model is not hidden, and §4 says "plan-level preconditions come before every per-tie reason: lockout, isolation, and the Q-DESIGN-2 section-load check", yet the carve-out puts a per-tie reason (FAULTED_SECTION) ahead of that plan-level check. Under STD-ARCH-4 the stated behaviour must be the governing one; under STD-GOV-3 a gate decision is not reinterpreted by an agent.

The Architect does not choose between the readings. Both outcomes are fail-safe (refuse vs. hold), so STD-ARCH-4 alone does not settle it; there is a possible tension between Q-DESIGN-2 ("any candidate section") and Q-DESIGN-3 ("the guard's behaviour must not change"). Resolution belongs to the Design stage: either conform to Q-DESIGN-2 as written (the section-load check also covers held ties, with REQ-TIECAP-21 left as Q-DESIGN-2 directs), or raise the held-tie + invalid-load case as a design question for the principal engineer and keep it open until answered.

### A-4 — STD-SAFETY-2 and STD-ARCH-6: the characterization base and the unit boundaries are not one revision

1. **Base revision.** Q-DESIGN-3 names draft PR #13. The design's measurement claim says "a prototype of this design on top of PR #13's branch (`agent/rca-backfeed/fix` @ 20d2a30) fails 19 of the 38 tests on that branch" (design line 10). Measured: that branch has **13** tests; 38 is `agent/rca-backfeed/integration` @ 5fdd0fb (PR #14). The third file the design lets U3 edit, `backend/tests/test_flisr_def_flisr_7_qa.py`, exists only in PR #14 (commit 5fdd0fb), not in PR #13 (design line 271 says the three files "come from PR #13"). The amended REQ-TIECAP-22 pins parity to "`main` @ 5f6b471 with DEF-FLISR-7 PR #13 merged", which is not a fixed revision. STD-SAFETY-2 needs the characterization oracle pinned on one named revision; the design must name it (a SHA) and say whether PR #14's QA file is part of it.
2. **Unit boundaries.** `units.json` on the design branch is unchanged from Decompose and contradicts the design: U1 "every test is written and run against main @ 5f6b471" (design: main with PR #13 merged); U2 reason enum has 4 members (design: 5, FAULTED_SECTION first); U3 `files` omits the three DEF-FLISR-7 test files the design says "U3 adds … to its file list". The Coding stage is bound by unit file lists, so as handed over the §6.1 edits to PR #13/#14 tests would be out of boundary, and REQ-TIECAP-11/22 trace to a unit scope that says otherwise (STD-ARCH-6: requirement → component → test must be consistent). The design must record these deltas as an explicit requirement on the Decompose artifact (or the run must re-decompose); the Architect does not edit `units.json`.

## Clause-by-clause check

| Clause | Result | Evidence |
|---|---|---|
| STD-ARCH-1 | Conforms (O-A) | Constants, `IsoAwareDatetime`, `TieCapacity`, `TieBlockReason`, `BlockedTie`, `RestorationPlan` fields in `models.py` (design §2); decisions in `flisr.py` (§3–4). `_require_iso_string` accepted as a type parser (attempt-1 O-1). |
| STD-ARCH-2 | Conforms under the scoped waiver | One production characteristic `tie_capacity_verdict`; one predicate `_not_finite_nonneg` shared by the verdict, the section check and the notes; parameters single-sourced in `models.py` (§3 consumer table), enforced by P1/P2. Oracle duplication waived per Q-DESIGN-1, confined to three files under `backend/tests` (§6.3). FAULTED_SECTION is not a verdict output, so the guard is not re-implemented. |
| STD-ARCH-3 | Conforms | `models` → pydantic/stdlib; `flisr` → `.models`, `.network` (as `flisr.py:11-17`); `api` → `.flisr`, `.models`, `.network` (as `api.py:8-10`). No upward import. |
| STD-ARCH-4 | **VIOLATION (A-3)**; otherwise conforms (O-B) | A-1 resolved. Held-tie invalid-load behaviour departs from Q-DESIGN-2. |
| STD-ARCH-5 | Conforms | §4 removed-guard table; PR #13 guard kept unchanged and first; the removed `.get(mrid, 0.0)` and `transferred > available` have replacements in the same change. |
| STD-ARCH-6 | **VIOLATION (A-2, A-4.2)** | Every REQ-TIECAP-1..23 id is mapped in §7 (checked id by id), but REQ-TIECAP-18's mapping contradicts the requirement for FAULTED_SECTION ties, and REQ-TIECAP-11/22 trace to unit scopes that `units.json` contradicts. |
| STD-ARCH-7 | Conforms | Review only; `design.md`, `specification.md`, `units.json` on this branch are byte-identical to `eb01c2a`. |
| STD-ARCH-8 | Conforms | No IEC 61850 LN/DO exposure; `blocked_ties` internal to the planner API. |
| STD-SAFETY-1 | Conforms | Safety-critical; `backend/app/flisr.py` protected, two human reviewers stated (header, U1–U4). `_isolation_switches` unchanged. |
| STD-SAFETY-2 | **VIOLATION (A-4.1)** | Characterization base revision not fixed (PR #13 vs PR #14; "PR #13 merged" not a SHA). Order (pin → repro → fix) otherwise correct (§6.1). The §6.1 edit rule for existing DEF-FLISR-7 tests keeps every switching step and count, which is acceptable with the PR explanation the skill requires. |
| STD-SAFETY-3 | Conforms | U1 `xfail(strict=True)` reproductions (no entry; legacy NaN/+inf) before any production edit. |
| STD-SAFETY-4 | Conforms except A-3 | Smallest fail-safe change; NaN/+inf close and implicit zero removed; out-of-range L and invalid section loads refuse the plan. |
| STD-SAFETY-5 | Conforms | U4 ≥ 500 seeded cases, ≥ 5 % each out-of-range L, negative section inside positive total, faults touching a tie's pick-up set; seed and count printed. |
| STD-SAFETY-6 | Conforms (per-unit waived by Q-SPEC-4) | Independent closed-form oracle (`oracle_*`) under `backend/tests`, not importing `app.flisr`/`app.network` or the constants (O1); boundaries §6.2; 0.5 kW engineering units. |
| STD-SAFETY-7 | Conforms | §8.1 tool-classification argument (agents T3-like, pytest/ruff/ast checks T2, pydantic/FastAPI as pre-existing software); no credit claimed. |
| STD-SAFETY-8 | Conforms | Local prototypes on synthetic data only; this review used only local worktrees. |
| STD-GOV-1/2 | Conforms | Design on `agent/feature-tie-capacity/design`, draft PR #15 with label `ai-generated`; commit `eb01c2a` carries the `AI-Governance` trailer. |
| STD-GOV-3 | **VIOLATION (A-3)** | Q-DESIGN-2 reinterpreted by the design. |
| STD-GOV-6 | Conforms | Two human reviewers for the protected path. |
| STD-GOV-7 | Note (O-C) | |

## Observations (no verdict impact)

- **O-A (STD-ARCH-1).** `FlisrRequest` in `api.py` now carries validators (`_no_null`, `_mutually_exclusive`). Accepted as an API-layer request DTO following `EstimationRequest`/`AgcRequest`; it holds input validation, not plant decisions.
- **O-B (STD-ARCH-4, minor).** `build_plan` with a non-datetime `as_of` (direct Python callers only) would fail at `as_of.astimezone(UTC)` before the verdict's precondition; the §4 table states only the naive case. Behaviour is still "raise, no plan" (fail-safe); state it.
- **O-C (STD-GOV-7).** The platform appends a `Co-Authored-By` trailer with a personal name and e-mail to agent commits (design `eb01c2a` and this review's commits). The agent cannot change the commit identity; carried forward as a compliance note.
- **O-D (REQ-TIECAP-12).** The FAULTED_SECTION note is PR #13's text, which names the tie and the reason in words but not the code `FAULTED_SECTION`, unlike the capacity notes. Acceptable as designed (code is in `blocked_ties`); reviewers may want consistency.

## Verify

- Every finding cites a clause and a measured or quoted source; none asks for scope outside the specification. A-3 asks the Design stage to conform to or question a recorded answer; the Architect does not decide it.
- No production or test code changed. `pytest backend -q` and `ruff check backend` re-run on `main` (2 passed; all checks passed).

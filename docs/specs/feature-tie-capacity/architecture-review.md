# Architecture review — FLISR restoration respects tie-switch capacity

Run: `feature-tie-capacity` · Stage: ARCHITECT · Attempt: 3 · Reviewed: `docs/specs/feature-tie-capacity/design.md`, `specification.md` amendments and `units.json` amendments @ `1238178` (design attempt 5, draft PR #15), against the declared base `agent/rca-backfeed/fix` @ `20d2a30` (PR #13) and `main` @ `5f6b471`
Standards: STD-ARCH v2.0, STD-SAFETY v3.1, STD-GOV v1.1 · Safety classification: **safety-critical**
Verdict: **VIOLATION** (1 finding with two parts: A-5 STD-ARCH-4 / STD-GOV-3 / STD-ARCH-6). Attempt-2 findings A-2 and A-4 are resolved. A-3 is resolved in the prose and the units, but the normative loop pseudocode still has the carve-out (A-5). The design was not edited (STD-ARCH-7).

## Prepare

- Standards loaded from the brief: STD-ARCH (v2.0), STD-SAFETY (v3.1), STD-GOV (v1.1).
- Repo instructions read: `.agents/skills/safety-critical-change/SKILL.md`, `DEMO_NOTES.md`.
- Layer map (brief): `ui → api → logic → models`. logic = `flisr.py`, `state_estimator.py`, `agc.py`, `network.py`, `savecase.py`; models = `models.py`; api = `api.py`.
- Baseline re-run this attempt on a worktree of `20d2a30`: `pytest backend -q` → **13 passed**, `ruff check backend` → all checks passed.

## Attempt-2 items

| Item | Status | Evidence |
|---|---|---|
| A-2 (STD-ARCH-6) | **Resolved** | REQ-TIECAP-18 amended in `specification.md` @ 1238178 (capacity-blocked: all candidate sections; FAULTED_SECTION: candidate sections other than the faulted one). This matches `flisr.py` @ 20d2a30 guard accounting (`section.mrid != faulted_section.mrid`). Measured: fault on `SEC-1201-04`, `customers_remaining` = 341. Design §4 row, §7 row and U3/U4 notes are consistent with it. |
| A-3 (STD-GOV-3, STD-ARCH-4) | **Partly resolved, see A-5** | The header, the §4 input table (line 169), the §4 "Integration with DEF-FLISR-7" paragraph (line 224), §6.3 (`oracle_sections_ok` checked before `oracle_held`), §8, §9, §10.2 and `units.json` U3/U4 now apply Q-DESIGN-2 to every candidate tie, before the guard. REQ-TIECAP-21 now has only the Q-DESIGN-3 amendment, as Q-DESIGN-2 directs. |
| A-4.1 (STD-SAFETY-2) | **Resolved** | Base named by SHA `20d2a303c9548f9f7170cb3dfef1487fb7e9a009` in the design header, REQ-TIECAP-22 and U1, with a base-drift STOP. PR #14's QA file is excluded. "5 of 13" re-measured: adding `as_of`, `blocked_ties` and `deprecations` to `RestorationPlan` on 20d2a30 fails exactly the 5 tests the design names (§6.1). |
| A-4.2 (STD-ARCH-6) | **Resolved** except U4, see A-5(b) | `units.json` @ 1238178: U1 base, U2 enum of 5 members, U3 files +2 base test files and +REQ-TIECAP-11, U3 loop-order note, U4 held-tie note. |
| O-B (STD-ARCH-4) | Resolved | §4 row for a non-datetime `as_of`. |
| O-C (STD-GOV-7) | Open (platform) | see Observations. |
| O-D (REQ-TIECAP-12) | Accepted | PR #13 note text unchanged; code in `blocked_ties`. |

## Finding (VIOLATION)

### A-5 — STD-ARCH-4, STD-GOV-3, STD-ARCH-6: the normative tie-loop pseudocode still exempts held ties from the Q-DESIGN-2 check

**(a) design.md.** Attempt 5 says the tie-loop order is "empty-candidate skip → section-load precondition (every candidate tie) → DEF-FLISR-7 guard → L precondition → `tie_capacity_verdict`". This appears in the §4 paragraph (line 224), in the §4 table (line 169, "held or not, checked before the guard") and in units.json U3. Other parts of the design still give the old order:

- **§4 "Tie loop" pseudocode (lines 183–188).** The loop that "replaces `flisr.py:92-121`" runs the guard first and ends its branch with `continue  # before any load or capacity evaluation`. The `for sec in sections …: raise FlisrError` check comes after that `continue`. Implemented as written, a held tie's pick-up sections are never checked, which is exactly the attempt-4 carve-out that A-3 rejected.
- **§7 row REQ-TIECAP-9 (line 327)**: "loop order: guard → section check → `tie_capacity_verdict`".
- **§9 Q-DESIGN-3 (line 374)**: "The guard runs before load and capacity evaluation". **§10.1 O-2 (line 389)**: "first in the loop and ahead of load and capacity evaluation".

Measured on the base @ 20d2a30, where the guard runs first and no load check exists, so this is the outcome the pseudocode keeps for a held tie. Setup: shipped `FDR-1201`, `CB-1201` open, fault indications on SEC-1201-01..03, so the fault is on `SEC-1201-04`; `TIE-1201-1405` = 2000 kW. With `SEC-1201-04.load_kw` = NaN, and again with −120.0, a plan **is returned**: restoration `[CB-1201 close]`, `customers_remaining` 341, the held-open note. Q-DESIGN-2 as written, and the design's own §4 table, require `FlisrError` with no plan.

The design states two different behaviours for the same input, so STD-ARCH-4 is not met: the stated behaviour must be the one that governs. The pseudocode is the part Coding implements, and it departs from the recorded human answer, which STD-GOV-3 forbids. The independent oracle (§6.3) uses the prose order, so QA would probably catch the difference. But the design is the contract and must not depend on QA to settle its own contradiction.

**(b) units.json U4.** The original U4 scope note was not amended: "The invariant is about capacity gating only; it must neither assert nor exclude DEF-FLISR-7 back-feed (spec section 3)". The amendment added next to it says "Held ties: FAULTED_SECTION whatever the capacity …", and design §7 REQ-TIECAP-21 says "no close step unless the tie is not held". So U4 now asserts the DEF-FLISR-7 hold, and its two scope notes contradict each other. The same applies to U3's unamended note "per-tie usability with precedence INVALID > UNKNOWN > STALE > EXCEEDED", which conflicts with the amended REQ-TIECAP-9 (FAULTED_SECTION first). The amended note is right next to it, so this one matters less. These are the unit-boundary consistency points A-4.2 asked for (STD-ARCH-6: requirement → component → test must agree).

**Resolution (Design stage; no new scope, no new question):**

1. Reorder the §4 pseudocode to match line 224: the section-load check for each candidate tie comes before the guard branch.
2. Make §7 REQ-TIECAP-9, §9 and §10.1 O-2 consistent with that order. Note that the guard still comes before L and capacity, but after the section-load check.
3. Mark the stale U4 and U3 scope notes in `units.json` as superseded, using the same `[Design attempt N amendment]` convention.

## Clause-by-clause check

| Clause | Result | Evidence |
|---|---|---|
| STD-ARCH-1 | Conforms | Constants, `IsoAwareDatetime`, `TieCapacity`, `TieBlockReason` (5), `BlockedTie` and the `RestorationPlan` fields are in `models.py` (§2). Decisions are in `flisr.py` (§3–4). `_require_iso_string` is a type parser (O-1). `FlisrRequest` is an API DTO (O-A). |
| STD-ARCH-2 | Conforms under the scoped waiver | One production characteristic, `tie_capacity_verdict`, and one predicate, `_not_finite_nonneg`. Parameters come only from `models.py`, enforced by P1/P2. The oracle restatement is waived per Q-DESIGN-1 and limited to three `backend/tests` files (§6.3). FAULTED_SECTION is not a verdict output. |
| STD-ARCH-3 | Conforms | `models` imports pydantic/stdlib only, `flisr` imports `.models` and `.network`, `api` imports `.flisr`, `.models` and `.network`. This matches the imports in `flisr.py`/`api.py` @ 20d2a30. No upward import. |
| STD-ARCH-4 | **VIOLATION (A-5a)** | The same input (a held tie with an invalid pick-up load) is stated two ways: §4 table/line 224 say `FlisrError`, the §4 pseudocode says plan returned. Every other row is stated. |
| STD-ARCH-5 | Conforms | §4 removed-guard table. The PR #13 guard is kept byte-for-byte, and its branch only adds a `blocked_ties.append`. |
| STD-ARCH-6 | **VIOLATION (A-5a §7 row, A-5b units)** | All REQ-TIECAP-1..23 are mapped in §7 (checked id by id). The REQ-TIECAP-9 component mapping gives the wrong order, and U4/U3 carry contradictory scope notes. |
| STD-ARCH-7 | Conforms | Review only. `design.md`, `specification.md` and `units.json` on this branch are byte-identical to `1238178` (`git diff 1238178` empty for the three files). |
| STD-ARCH-8 | Conforms | No IEC 61850 LN/DO exposure. |
| STD-SAFETY-1 | Conforms | Safety-critical. Protected `backend/app/flisr.py` needs two human reviewers (header, U1–U4). |
| STD-SAFETY-2 | Conforms | The characterization base is pinned by SHA with a drift STOP. The §6.1 edit rule for the 5 affected base tests keeps every step and count unchanged. |
| STD-SAFETY-3 | Conforms | U1 reproductions re-measured on 20d2a30, shipped model, `CB-1201` open, fault on SEC-1201-03. No entry: tie skipped with no machine-readable reason. Legacy NaN and +inf: `TIE-1201-1405` **closed**, `customers_restored` 341. Both fail as `xfail(strict=True)` intends. |
| STD-SAFETY-4 | Conforms in the prose; at risk through A-5a | Fail-safe preconditions and per-tie blocking. A held tie with an invalid load must refuse the plan, as Q-DESIGN-2 requires. |
| STD-SAFETY-5 | Conforms | U4 has ≥ 500 seeded cases, with ≥ 5 % each of out-of-range L, a negative section inside a positive total, and held ties. Seed and count are printed. |
| STD-SAFETY-6 | Conforms (per-unit waived by Q-SPEC-4) | Independent `oracle_*` (§6.3), O1 import/constant check, boundaries in §6.2, 0.5 kW in engineering units. |
| STD-SAFETY-7 | Conforms | §8.1 tool-classification argument. No credit claimed. |
| STD-SAFETY-8 | Conforms | Local worktrees and synthetic model copies only. |
| STD-GOV-1/2 | Conforms | `agent/feature-tie-capacity/design`, draft PR #15. Commit `1238178` has the `AI-Governance` trailer. |
| STD-GOV-3 | **VIOLATION (A-5a)** | The pseudocode departs from the recorded Q-DESIGN-2 answer. |
| STD-GOV-6 | Conforms | Two human reviewers for the protected path. |
| STD-GOV-7 | Note (O-C) | |

## Observations (no verdict impact)

- **O-C (STD-GOV-7).** The platform appends a `Co-Authored-By` trailer with a personal name and e-mail to agent commits (design `1238178` and this review's commits). The agent cannot change the commit identity. Carried forward as a compliance note.
- **O-E (blast radius).** Applying Q-DESIGN-2 before the guard means a fault whose held tie's pick-up set (faulted section included) has an invalid load now returns 409 and no plan, where PR #13 returns isolation steps. The design states this blast radius (§4), and reviewers should confirm it. It follows from the recorded answer, so it is not a finding.

## Verify

- Every finding cites a clause and a measured or quoted source (line numbers in `design.md` @ 1238178, scope notes in `units.json` @ 1238178, plans measured on 20d2a30). None asks for scope outside the specification. The resolution only aligns the design with its own stated order and with Q-DESIGN-2. The Architect makes no design choice.
- No production or test code changed. Base re-run: `pytest backend -q` 13 passed, `ruff check backend` all checks passed (20d2a30). The prototype edit used to re-measure "5 of 13" was reverted in a throw-away worktree.

---

# Architecture review — attempt 4 (Design attempt 6 @ 8d49338)

**Verdict: VIOLATION** (one finding, A-6). Reviewer did not edit design.md, units.json, specification.md, code or tests (STD-ARCH-7).

Standards loaded: STD-ARCH v2.0, STD-GOV v1.1, STD-SAFETY v3.1. Repo contract read: `.agents/skills/safety-critical-change/SKILL.md`, `DEMO_NOTES.md`, layer map `ui → api → logic → models`.

## A-5 (attempt 3) — resolved

- A-5(a): §4 pseudocode, the §4 table, the "Integration with DEF-FLISR-7" paragraph and units.json U3 now all give one order: empty-candidate skip → section-load check (every candidate tie, held or not → `FlisrError`) → DEF-FLISR-7 guard → L precondition → `tie_capacity_verdict`.
- A-5(b): the stale U3 note is marked `[SUPERSEDED …]` and the replacement note follows it (history kept, STD-GOV-4).
- Measured on the base (20d2a30) with the section-load check put before the guard (scratch copy, not committed). Fault SEC-1201-04, lockout CB-1201, TIE-1201-1405 C = 2000:
  - SEC-1201-04 `load_kw` = NaN / +inf / −inf / −120.0 → base returns a plan (CB-1201 close only, tie held); prototype raises `FlisrError`. This matches Q-DESIGN-2.
  - All loads valid → prototype plan = base plan (CB-1201 close, tie held, guard note, `customers_remaining` 341).
  - Base suite with the prototype `flisr.py`: `13 passed, 1 warning`. The guard is unchanged for valid-load plans (STD-ARCH-5, STD-SAFETY-4).

## A-6 (new) — REQ-TIECAP-3 still requires closing a held tie — VIOLATION

Clauses: STD-ARCH-6 (each requirement maps to a component and test that can meet it), STD-ARCH-4 (fail-safe default), STD-GOV-3 (Q-DESIGN-3 is a human decision: FAULTED_SECTION first, the guard does not change).

- specification.md REQ-TIECAP-3 (not amended): "For a candidate tie with usable capacity C, `build_plan` shall emit a `close` restoration step for that tie **if and only if** `L ≤ C + 0.5 kW`."
- REQ-TIECAP-21 (amended per Q-DESIGN-3): "A tie whose pick-up set contains an endpoint of the faulted section is FAULTED_SECTION and is **never closed**." Design §4: the guard `continue`s before `tie_capacity_verdict`.
- REQ-TIECAP-9 sets which reason is *recorded*. It does not cancel the "if" half of REQ-TIECAP-3's "iff", which requires a close step.
- Measured counter-example (base 20d2a30, scenario as above). The tie's candidate set has L = 1490 kW (`load_on_nodes`) and legacy C = 2000 (GOOD at `as_of`), so capacity is usable and 1490 ≤ 2000.5. REQ-TIECAP-3 requires a close step. The guard (and the design) emits none. Output: `restoration [('CB-1201','close')]`, note "…TIE-1201-1405 held open: would back-feed faulted section…".
- Design §7 row REQ-TIECAP-3 maps it to `tie_capacity_verdict` with no guard exception. A Coding or QA stage on another model that writes REQ-TIECAP-3 literally would close onto the fault and regress DEF-FLISR-7. That is unsafe.
- Q-DESIGN-3 already led to amending REQ-TIECAP-9, -11, -18, -21 and -22. REQ-TIECAP-3 was left out.

**Severity: high.** Literal compliance closes a tie onto a faulted section (back-feed). The fix is one clause.

**Resolution (for Design; the reviewer does not edit):** amend REQ-TIECAP-3 (and REQ-TIECAP-4, which has the same scope) to apply to candidate ties not held by the DEF-FLISR-7 guard (Q-DESIGN-3), and update the §7 rows to match. Nothing else in the design has to change.

## Clause check (attempt 6)

| Clause | Result | Evidence |
|---|---|---|
| STD-ARCH-1 | OK | §2/§3: constants and pydantic models only in `models.py`, no control flow |
| STD-ARCH-2 | OK | one production `tie_capacity_verdict`; scoped waiver for QA oracles in §6.3 (Q-DESIGN-1) |
| STD-ARCH-3 | OK | api → flisr/network/models; flisr → network/models; network → models; models imports nothing upward; console unchanged |
| STD-ARCH-4 | **A-6** | otherwise absent/stale/out-of-range are specified per function (§3, §4, §5) with fail-safe defaults |
| STD-ARCH-5 | OK | the implicit-0 default is replaced by CAPACITY_UNKNOWN; the guard is kept byte-for-byte; the existing `transferred > available` refusal is kept in `tie_capacity_verdict` |
| STD-ARCH-6 | **A-6** | REQ-TIECAP-1..23 each have a component and a test strategy in §7; REQ-TIECAP-3's requirement contradicts REQ-TIECAP-21 |
| STD-ARCH-7 | OK | review only; no design edits |
| STD-ARCH-8 | OK / N/A | no IEC 61850 exposure |
| STD-SAFETY-1 / STD-GOV-6 | OK | `backend/app/flisr.py` protected; two human reviewers required; PR #15 is draft |
| STD-SAFETY-2..6 | OK (planned) | U1 characterization on 20d2a30 + failing reproductions; U3 minimal fix; U4 ≥ 500 seeded; independent BFS/closed-form oracle with 0.5 kW tolerance. Plans only, not executed evidence |
| STD-SAFETY-7/8 | OK | tool classification in §8; no production systems, secrets or devices |

Observation (non-blocking): U1 notes [2]–[4] still say "today"/"main". [0] pins the base, so behaviour is unaffected.

Baseline @ 20d2a30: `PYTHONPATH=backend python -m pytest backend -q` → 13 passed, 1 warning; `ruff check backend` → All checks passed!

---

# Architecture review — attempt 5 (Design attempt 7 @ de7e75c)

**Verdict: CONFIRMED.** No violation. A-6 is resolved. The reviewer did not edit design.md, specification.md, units.json, decomposition.md, code or tests (STD-ARCH-7): after merging de7e75c into this branch, `git diff de7e75c HEAD` is empty for all four files.

## Prepare

- Standards loaded from the brief: STD-ARCH v2.0 (STD-ARCH-1..8), STD-SAFETY v3.1 (STD-SAFETY-1..8), STD-GOV v1.1 (STD-GOV-1..7).
- Repo instructions read: `.agents/skills/safety-critical-change/SKILL.md`, `DEMO_NOTES.md`. Layer map (brief): `ui → api → logic → models`.
- Inputs checked against the remote: `main` = 5f6b471, the PR #13 head (`agent/rca-backfeed/fix`) is still 20d2a303c9548f9f7170cb3dfef1487fb7e9a009 (no base drift), PR #14 head = 44d9031, design PR #15 = draft @ de7e75c with label `ai-generated`. Commit de7e75c has the `AI-Governance` trailer.
- Baseline on a throw-away worktree of 20d2a30: `PYTHONPATH=backend python -m pytest backend -q` → 13 passed, 1 warning. `ruff check backend` → All checks passed!

## A-6 (attempt 4): resolved

- `specification.md` REQ-TIECAP-3 and REQ-TIECAP-4 are now scoped to candidate ties whose pick-up set contains no endpoint of the faulted section. Each carries an inline amendment marker citing Q-DESIGN-3. A held tie is "never closed, whatever its capacity" and is recorded FAULTED_SECTION. A held tie with `L > C + 0.5` is FAULTED_SECTION, not EXCEEDED. The "if" half of the "iff" therefore no longer requires closing a held tie. REQ-TIECAP-3 and REQ-TIECAP-21 now agree.
- Spec §2 item 2 (the more-permissive τ window) and the §4 oracle note are scoped the same way. The §3 docstring of `tie_capacity_verdict` says it is never called for a held tie. The §7 rows for REQ-TIECAP-3/4 map to guard-then-verdict and add held-tie tests (C = 2000.0 GOOD and C = 10.0 GOOD → FAULTED_SECTION only).
- `units.json`: the U3 attempt-6 loop note is marked SUPERSEDED and followed by its replacement. The U3 and U4 oracles name the held-tie check before capacity. The JSON parses (U1 has 10 notes, U2 3, U3 10, U4 5).
- Grep of `design.md`, `specification.md` and `units.json` for "if and only if", "close iff" and "closes iff": every live hit is scoped to ties not held. The only other hits are SUPERSEDED notes and the history tables.
- The other requirements that name a capacity reason (REQ-TIECAP-5..8) all say "emit no step", which is consistent with the hold. Which reason gets recorded is settled by the amended REQ-TIECAP-9 ("record only the first", FAULTED_SECTION first). This is the same structure the spec already used for INVALID vs UNKNOWN, so no further amendment is needed.
- Measured on the base 20d2a30 (shipped `FDR-1201`, `CB-1201` open, legacy map; read-only script, nothing committed):

| Input | Faulted | Restoration | customers_remaining / restored | Note |
|---|---|---|---|---|
| shipped indicators, no entry | SEC-1201-03 | CB-1201 close | 437 / 0 | "…skipped: 1490 kW exceeds 0 kW…" |
| shipped indicators, NaN | SEC-1201-03 | CB-1201, **TIE-1201-1405 close** | 96 / 341 | none |
| shipped indicators, 1489.5 | SEC-1201-03 | CB-1201 close | 437 / 0 | "…1490 kW exceeds 1490 kW…" |
| fault on SEC-1201-04, C = 2000 | SEC-1201-04 | CB-1201 close | 341 / 0 | held open: would back-feed SEC-1201-04 |
| fault on SEC-1201-04, C = 10 | SEC-1201-04 | CB-1201 close | 341 / 0 | held open |
| fault on SEC-1201-04, SEC-1201-04 load NaN | SEC-1201-04 | CB-1201 close | 341 / 0 | held open (the design turns this into `FlisrError`, Q-DESIGN-2) |

  These rows match what the design and the amended spec state: the U1 repro (a)/(b) inputs are not held, the 1489.5 row is intended change 2, the held rows become FAULTED_SECTION, and the Q-DESIGN-2 row becomes no plan.

## Clause check (design attempt 7)

| Clause | Result | Evidence |
|---|---|---|
| STD-ARCH-1 | Conforms | design §2: constants, `IsoAwareDatetime`, `TieCapacity`, `TieBlockReason` (5), `BlockedTie` and the `RestorationPlan` fields live in `models.py` with no control flow. `_require_iso_string` is a type parser (O-1). `FlisrRequest` is an API DTO in `api.py`, following the existing convention. |
| STD-ARCH-2 | Conforms under the scoped waiver | One production characteristic (`tie_capacity_verdict`) and one predicate (`_not_finite_nonneg`). Parameters come only from `models.py`, enforced by P1/P2. The test-oracle restatement is waived per Q-DESIGN-1 (§6.3, O1). FAULTED_SECTION is not a verdict output. |
| STD-ARCH-3 | Conforms | `models` imports pydantic/stdlib only. `flisr` imports `.models`/`.network` (matches `flisr.py` @ 20d2a30). `api` imports `.flisr`/`.models`/`.network`. `console/**` is unchanged. No upward import. |
| STD-ARCH-4 | Conforms | §3 verdict preconditions and decisions; §4 table (both maps, `as_of` absent/naive/non-datetime, legacy, wrong type, invalid section load for every candidate tie, L overflow, held tie, non-candidate entry, lockout, no fault); §5 endpoint. Every row fails safe. No input has two stated behaviours: the A-5 order and the A-6 scope are consistent across §3, §4, §7, §9, the units and the spec. |
| STD-ARCH-5 | Conforms | §4 removed-guard table. The implicit 0 kW default is replaced by CAPACITY_UNKNOWN. The `transferred > available` refusal is kept as the verdict's positive close condition. The PR #13 guard is kept byte-for-byte (its branch only adds `blocked_ties.append`). The §6.1 edit rule for the 5 affected base tests changes no step or count. |
| STD-ARCH-6 | Conforms | §7 maps REQ-TIECAP-1..23 one by one, each to a component and a test (checked id by id). The REQ-TIECAP-3/4/9/11/18/21/22 amendments are marked in the spec and traced in §9/§10.4/§11. The unit boundaries in `units.json` match the design. |
| STD-ARCH-7 | Conforms | Review only (see the verdict line above). |
| STD-ARCH-8 | Conforms / N/A | No IEC 61850 LN/DO exposure. `blocked_ties` is internal to the planner API. |
| STD-SAFETY-1 / STD-GOV-6 | Conforms | Safety-critical. Protected `backend/app/flisr.py` needs two human reviewers (design header, U1–U4). |
| STD-SAFETY-2 | Conforms (planned) | U1 characterization is pinned on 20d2a30 by SHA, with a base-drift STOP. Measured: no drift. |
| STD-SAFETY-3 | Conforms (planned) | Repros (a) no entry and (b) legacy NaN/+inf on shipped indicators (SEC-1201-03, tie not held) fail on the base as `xfail(strict=True)` intends (table above). |
| STD-SAFETY-4 | Conforms | Smallest change in the tie loop. Refusal or block on every ambiguous input. Held ties are never closed. |
| STD-SAFETY-5 | Conforms (planned) | U4: ≥ 500 seeded cases with any-node ties and faults, ≥ 5 % each of out-of-range L, a negative section inside a positive total, and held ties. Seed and count are printed. |
| STD-SAFETY-6 | Conforms (per-unit waived by Q-SPEC-4) | Independent `oracle_*` under `backend/tests` (§6.3), with O1 import/constant check and oracle self-check. The held-tie check comes before capacity. Tolerance 0.5 kW in engineering units. |
| STD-SAFETY-7 | Conforms | §8.1 tool-classification argument (agents T3-like; pytest/ruff/ast checks T2). No credit claimed. |
| STD-SAFETY-8 | Conforms | Local worktrees and synthetic model copies only. |
| STD-GOV-1/2 | Conforms | `agent/` branches; draft PR #15 with label `ai-generated`; trailer on de7e75c and on this review's commits. |
| STD-GOV-3 | Conforms | REQ-TIECAP-3/4 now follow Q-DESIGN-3 as written. Q-DESIGN-1/2 are applied as answered. No decision is inferred. |
| STD-GOV-7 | Note (O-C) | see Observations. |

## Observations (no verdict impact)

- **O-C (STD-GOV-7, platform).** The platform still appends a `Co-Authored-By` trailer with a personal name and e-mail to agent commits (de7e75c and this review's commits). The agent cannot change the commit identity. Carried forward for a human to resolve.
- **O-F (wording).** design.md §3, decision "Out-of-range L is refused", says "the four reasons describe C, not L. Adding a fifth reason would change REQ-TIECAP-11". REQ-TIECAP-11 now has five members, so the sentence should say "the four capacity reasons … adding another reason". This is rationale text only. The behaviour (L out of range → `FlisrError`, never a `BlockedTie`) is stated consistently elsewhere.
- **O-G (audit trail).** The U3/U4 `oracle` strings in `units.json` were replaced in place with the `[Design attempt 7 amendment, A-6]` prefix, unlike scope notes, which keep the superseded text. The previous text is still in git (8d49338) and summarised in design §11, so this is acceptable, but Integrate should not rely on `units.json` alone for oracle history.
- **O-E (blast radius, unchanged).** A held tie whose pick-up set has an invalid load now returns 409 and no plan where PR #13 returns isolation steps. Spec §2 item 5 (the 80 s residual back-dating window) and item 2 (the τ window) also still need reviewer confirmation. All three are stated in the artifacts.
- **Out of scope, still unfixed (spec §3):** a manual (non-SCADA) upstream switch means the lockout reclose re-energises the fault (`_isolation_switches`), and `customers_remaining` is per tie, so it can double-count sections shared by several blocked ties (Q-SPEC-7 exclusion). The design does not need to address either; both should be tracked as separate defects.

## Verify

- Every clause above cites a design section, spec row, unit note or measurement. No finding asks for anything outside the specification's scope.
- No production or test code was changed. The base re-run is green (13 passed; ruff clean). The measurement script was read-only on a worktree, and the worktree was removed.

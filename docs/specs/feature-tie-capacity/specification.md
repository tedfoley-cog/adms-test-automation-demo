# Specification — FLISR restoration respects tie-switch capacity

Run: `feature-tie-capacity` · Stage: SPECIFY · Attempt: 2 · Status: **BLOCKED** (open questions Q-SPEC-9, Q-SPEC-10, Q-SPEC-11)

## 0. Source, inputs and classification

- Source: change request "respect tie-switch capacity during FLISR restoration" plus human answers Q-SPEC-1..Q-SPEC-8 (ops-lead-standin).
- Safety classification (STD-REQ-6): **safety-critical** (IEC 61508-3 context). The change alters which tie switches FLISR commands closed. Every unit derived from this specification inherits the classification. `backend/app/flisr.py` is a protected path and needs two human reviewers (STD-GOV-6, STD-SAFETY-1).
- Scope (Q-SPEC-8): `build_plan` in `backend/app/flisr.py`, `POST /flisr/plan` in `backend/app/api.py`, and new types in `backend/app/models.py`.

### Current behaviour (baseline, `main` @ 5f6b471)

- `build_plan(feeder, lockout_switch_mrid, tie_capacity_kw: dict[str, float] | None)`. A tie with no entry reads as `0.0` kW (`flisr.py:98`, `tie_capacity_kw.get(switch.mrid, 0.0)`). That is an implicit "treat as zero", which STD-REQ-3 forbids.
- A tie is skipped when `transferred > available` (strict). Equality closes. There is no tolerance.
- On the shipped model with `CB-1201` open and no capacity supplied, the plan isolates `SEC-1201-03` (opens `SEC-SW-1201-1` and `REC-1201-2`), re-closes `CB-1201` and skips `TIE-1201-1405` with the note `"Hollow Creek tie to 1405 skipped: 1490 kW exceeds 0 kW available capacity"`. The results are `customers_remaining = 437` and `customers_restored = 0`.
- There is no timestamp, no quality and no machine-readable reason for a skipped tie.

### Definitions

- **Tie**: a `Switch` with `kind == tie` and `scada_controllable == True` for which `_nodes_restored_by` returns a non-empty candidate node set. Other ties are out of scope (see §3). Today they are skipped silently, and that does not change.
- **L (transferred load)**: the sum of `Section.load_kw` over the sections whose `to_node` is in the tie's candidate node set. Unit kW. Range L ≥ 0.
- **C (tie capacity)**: the alternate feeder's spare capacity as delivered by the SCADA scan every 10 s. Unit kW, on the same basis as `load_kw`. No unit conversion and no per-unit base (Q-SPEC-1). It is not a nameplate rating.
- **Tolerance τ**: 0.5 kW. This is the only tolerance and no other safety margin applies (Q-SPEC-1, Q-SPEC-4). Per-unit statement waived by human answer Q-SPEC-4.
- **t_eval**: the instant against which a capacity value's age is judged. Its source is open (Q-SPEC-10).
- **age**: `t_eval − TieCapacity.timestamp`, in seconds.
- **Usable capacity**: an entry that is present, has `quality == "GOOD"` and `age ≤ 20 s` (Q-SPEC-2), and is not invalid (definition open, Q-SPEC-9).

## 1. Requirements

| ID | Requirement (one testable statement) | Inputs → outputs | Missing / late / invalid behaviour | Verification (oracle) | Depends on open Q |
|---|---|---|---|---|---|
| REQ-TIECAP-1 | `backend/app/models.py` shall define a Pydantic model `TieCapacity` with the fields `kw: float` (kW, same basis as `Section.load_kw`), `timestamp: datetime` and `quality: str`. | — → type | A field that is missing from a `TieCapacity` fails model validation. Value validity is covered by REQ-TIECAP-8. | Test: construction and validation unit tests; inspection of `models.py`. | — |
| REQ-TIECAP-2 | `flisr.build_plan` shall accept `tie_capacity: dict[str, TieCapacity] \| None`, keyed by tie switch mRID. | feeder, lockout mRID, tie_capacity → `RestorationPlan` | `None` or `{}` means no tie has a known capacity, so every tie falls under REQ-TIECAP-5. | Test. | — |
| REQ-TIECAP-3 | For a tie with usable capacity C, `build_plan` shall emit a `close` restoration step for that tie **if and only if** `L ≤ C + 0.5 kW`. | L, C → close step present / absent | If C is not usable, REQ-TIECAP-5..8 apply and the tie is never closed. | Test against an independent closed-form oracle: the QA test computes L itself with a BFS over the test topology (not `network.load_on_nodes` or `_nodes_restored_by`) and evaluates `L_oracle ≤ C + 0.5`. Boundary cases on the shipped model (L = 1490 kW): C = 1490.0 closes, C = 1489.5 closes (L = C + τ), C = 1489.4 does not close (blocked as CAPACITY_EXCEEDED). Tolerance 0.5 kW engineering units; per-unit waived (Q-SPEC-4). | — |
| REQ-TIECAP-4 | For a tie with usable capacity and `L > C + 0.5 kW`, `build_plan` shall emit no step for that tie and shall record `BlockedTie(tie_id=<mRID>, reason=CAPACITY_EXCEEDED)`. It shall not pick up part of the load (Q-SPEC-6). | L, C → blocked_ties entry | — | Test (same oracle as REQ-TIECAP-3). | — |
| REQ-TIECAP-5 | For a tie with no entry in `tie_capacity` (including `tie_capacity` None or empty), `build_plan` shall emit no step for that tie and shall record `BlockedTie(reason=CAPACITY_UNKNOWN)`. The missing value shall never be read as 0 kW or any other value. | absent entry → blocked_ties entry | Missing → refuse for that tie only. | Test: missing key and `None`; inspection that no default capacity value remains (`flisr.py:98`). | — |
| REQ-TIECAP-6 | For a tie whose entry has `age > 20 s`, `build_plan` shall not use the value, shall emit no step for that tie and shall record `BlockedTie(reason=CAPACITY_STALE)`. An entry with `age ≤ 20 s` (so exactly 20 s is still fresh) is usable if REQ-TIECAP-7 and REQ-TIECAP-8 are also met. | timestamp, t_eval → usable / blocked | Late → refuse for that tie. A future timestamp (age < 0) and a timezone-naive timestamp are undefined (Q-SPEC-10). | Test with an injected t_eval: ages 19.999 s, 20.000 s (usable), 20.001 s (stale). Oracle: closed-form `age > 20`. | Q-SPEC-10 |
| REQ-TIECAP-7 | For a tie whose entry has `quality != "GOOD"` (exact match), `build_plan` shall not use the value, shall emit no step for that tie and shall record a `BlockedTie`. Which reason code applies (CAPACITY_UNKNOWN or CAPACITY_INVALID), and which reason wins when several conditions hold at once, is open. | quality → usable / blocked | Bad or uncertain quality → refuse for that tie (Q-SPEC-2). | Test. | Q-SPEC-9 |
| REQ-TIECAP-8 | For a tie whose entry holds an invalid value, `build_plan` shall emit no step for that tie and shall record `BlockedTie(reason=CAPACITY_INVALID)`. What counts as invalid (NaN, ±inf, negative kW, …) is open, and so is whether malformed HTTP input is a 422 or a per-tie CAPACITY_INVALID. | kw → usable / blocked | Invalid → refuse for that tie. Never clamp and never substitute a value. | Test. | Q-SPEC-9 |
| REQ-TIECAP-9 | A blocked tie shall not change the plan's isolation steps, the lockout re-close step, or how any other tie is evaluated (per-tie blocking, Q-SPEC-5). | per-tie inputs → plan | — | Test: a two-tie generated topology with one tie usable and one blocked. Compare isolation and the other tie's step against the same plan built without the blocked tie's problem. | — |
| REQ-TIECAP-10 | `RestorationPlan` shall gain `blocked_ties: list[BlockedTie]`, where `BlockedTie{tie_id: str, reason}` and `reason` ∈ {CAPACITY_UNKNOWN, CAPACITY_STALE, CAPACITY_INVALID, CAPACITY_EXCEEDED}. It holds exactly one entry per blocked tie and is empty when no tie is blocked. | — → plan field | — | Test (schema plus content). Inspection of `models.py`. | — |
| REQ-TIECAP-11 | For each blocked tie, `RestorationPlan.notes` shall contain one operator-readable entry naming the tie (`Switch.name`) and the reason. For CAPACITY_EXCEEDED it shall also give L and C in kW, and for CAPACITY_STALE the age in seconds. | blocked tie → note | — | Test (content asserted per reason). | — |
| REQ-TIECAP-12 | For a blocked tie, `build_plan` shall add the customers of the candidate sections to `customers_remaining` and shall add nothing to `customers_restored` or `transferred_load_kw`. For a closed tie the accounting stays as it is today. | plan totals | — | Test. Oracle: independent sums over the test topology. | — |
| REQ-TIECAP-13 | `POST /flisr/plan` shall accept a `tie_capacity` object mapping tie mRID → `TieCapacity`. When one or more ties are blocked it shall return HTTP 200 with the plan, including `blocked_ties`. It shall not return 409 for a blocked tie (Q-SPEC-5). The existing 404 (unknown feeder) and 409 (`FlisrError`) behaviour stays the same. | HTTP body → HTTP status + plan | Malformed `TieCapacity`: open (Q-SPEC-9 d). | Test (FastAPI `TestClient`). | Q-SPEC-9 (malformed only) |
| REQ-TIECAP-14 | For one release, `build_plan` and `POST /flisr/plan` shall still accept the legacy `dict[str, float]`. Each value shall be treated as `TieCapacity(kw=value, timestamp=t_eval, quality="GOOD")`, and the caller shall get a deprecation note (Q-SPEC-3). The body field shape, what happens when both forms are supplied, and where the deprecation note goes are open. | legacy map → same decisions as REQ-TIECAP-3..12 | A tie missing from the legacy map → CAPACITY_UNKNOWN (REQ-TIECAP-5). An invalid legacy value is handled per Q-SPEC-9. | Test. | Q-SPEC-9, Q-SPEC-11 |
| REQ-TIECAP-15 | When no fault indication is present (`faulted_section is None`), the plan shall be as it is today (no isolation, no restoration, manual-patrol note) with `blocked_ties` empty. | — | — | Test (characterization). | — |
| REQ-TIECAP-16 | t_eval shall be taken once per `build_plan` call, so every tie in one plan is judged against the same instant. | — | Source of t_eval (wall clock or injected) and the reference timezone are open. | Test and inspection. | Q-SPEC-10 |
| REQ-TIECAP-17 | Safety invariant: no plan shall contain a `close` step for a tie unless that tie's capacity is usable and `L ≤ C + 0.5 kW`. Every tie of the kind defined in §0 that is not closed shall appear exactly once in `blocked_ties`. | generated feeders + capacity maps → plans | Covers missing, stale, bad-quality and invalid entries. | Test (STD-SAFETY-5): at least 500 seeded `random` cases over radial and branched topologies with one or more ties, and capacity entries drawn across the missing / stale / boundary-age / non-GOOD / invalid / below / at / above `L + τ` classes. The QA-owned BFS oracle of REQ-TIECAP-3 recomputes L. | Q-SPEC-9, Q-SPEC-10 (for the invalid and future-time classes) |
| REQ-TIECAP-18 | For inputs where every tie has usable capacity and `L ≤ C` or `L > C + 0.5 kW`, the isolation steps, the restoration steps and their order, `customers_restored`, `customers_remaining` and `transferred_load_kw` shall equal the values on `main` @ 5f6b471. | — | — | Test: `@pytest.mark.characterization` tests pinned on unmodified code before any change (STD-SAFETY-2). | — |

### Intended behaviour changes (blast radius)

1. A tie with no capacity entry used to be skipped with a "0 kW available" note. It is now blocked with reason CAPACITY_UNKNOWN (REQ-TIECAP-5). The step and the accounting are the same; the note text and `blocked_ties` are new.
2. `C < L ≤ C + 0.5 kW` used to skip the tie and now closes it (REQ-TIECAP-3, Q-SPEC-1/Q-SPEC-4). This is the **only** change that makes the planner more permissive. Reviewers should confirm it was intended.
3. A value that is stale or not GOOD used to be impossible to express. It now blocks the tie.
4. The `RestorationPlan` schema gains `blocked_ties`, an additive field.

## 2. Open questions (STD-REQ-4) — not resolved by assumption

- **Q-SPEC-9: when CAPACITY_INVALID applies, which reason a non-GOOD quality gets, and precedence.** (a) Which `kw` values are invalid: NaN, ±inf, negative? A negative spare capacity could be a real reading (the alternate feeder is already overloaded) or a bad one. With `L = 0 kW` candidate sections and `C = −0.3`, REQ-TIECAP-3 would close the tie unless negative values are invalid. (b) Does `quality != GOOD` give CAPACITY_UNKNOWN (Q-SPEC-2 calls it "unknown") or CAPACITY_INVALID? (c) `BlockedTie` carries one reason. When several conditions hold (for example stale and not GOOD and NaN), which reason is recorded? (d) A structurally malformed entry in the HTTP body (for example a string `kw` or a missing `quality`): reject the whole request with 422, or block only that tie with CAPACITY_INVALID and return 200? Blocks: REQ-TIECAP-7, REQ-TIECAP-8, REQ-TIECAP-13 (malformed input only), REQ-TIECAP-14 (legacy validity), REQ-TIECAP-17.
- **Q-SPEC-10: time reference.** (a) Is t_eval the planner's own wall clock (UTC) when `build_plan` starts, or an evaluation time supplied by the caller or injected? (b) A timestamp later than t_eval (clock skew between the SCADA front end and the planner): usable, stale, or invalid? Is any skew allowed? Without a rule, a future-dated value would look fresh indefinitely. (c) A timezone-naive timestamp: reject, or interpret as UTC? Blocks: REQ-TIECAP-6, REQ-TIECAP-16, REQ-TIECAP-17.
- **Q-SPEC-11: legacy format alongside the new one.** (a) HTTP body: keep the legacy floats under `tie_capacity_kw` next to the new `tie_capacity`, or have one field accept either shape? (b) If both forms are supplied in one call, or for the same tie: refuse, let the new form win, or something else? (c) Where does the "deprecation note" go: `RestorationPlan.notes` (shown to operators), an HTTP `Deprecation` header, OpenAPI `deprecated`, a log line, or several of these? Blocks: REQ-TIECAP-14.

## 3. Scope exclusions (STD-REQ-7)

- The SCADA adapter and telemetry ingestion: scan scheduling, quality mapping and timestamping (integration team, Q-SPEC-3).
- Spare capacity on one alternate feeder shared by several ties (Q-SPEC-7). Each tie is checked independently.
- Partial pick-up or load shedding to fit within capacity (Q-SPEC-6).
- Nameplate or thermal rating of the tie switch, unit conversion, per-unit bases, and any safety margin beyond τ = 0.5 kW (Q-SPEC-1, Q-SPEC-4).
- Removing the legacy `dict[str, float]` input (a later release).
- `locate_fault` and fault-location logic (open PRs #8 and #11). `_isolation_switches` and DEF-FLISR-7 (a tie that is an isolation point back-feeds the faulted section) are a separate defect run. This change shall not fix or mask DEF-FLISR-7.
- Ties that are not SCADA-controllable, and ties with an empty candidate node set. Both are skipped silently as today and are not listed in `blocked_ties`.
- `console/**`. The console does not call `/flisr/plan` today. `state_estimator.py`, `agc.py`, `savecase.py`, `firmware/**` and `legacy/**` are also out of scope.

## 4. Verification notes for QA

- The independent oracle for the close/block decision is a QA-owned BFS over the test topology plus the closed-form checks `L ≤ C + 0.5`, `age > 20` and `quality == "GOOD"`. It must not import `app.network` or `app.flisr` helpers.
- Tolerance: 0.5 kW engineering units. A per-unit tolerance was waived by the human answer to Q-SPEC-4. QA should record that waiver against STD-SAFETY-6.
- Order of work under `.agents/skills/safety-critical-change/SKILL.md`: baseline, then characterization (REQ-TIECAP-15, REQ-TIECAP-18), then a failing reproduction (missing capacity read as 0 kW and no machine-readable reason), then the minimal fix, then the invariant (REQ-TIECAP-17, at least 500 seeded cases).
- Tool classification (STD-SAFETY-7) is the assessor's finding. The specification takes no tool-certification credit.

# Specification — FLISR restoration respects tie-switch capacity

Run: `feature-tie-capacity` · Stage: SPECIFY · Attempt: 3 · Status: **BLOCKED** (open questions Q-SPEC-12, Q-SPEC-13; every other requirement is complete)

## 0. Source, inputs and classification

- Source: change request "respect tie-switch capacity during FLISR restoration", plus human answers Q-SPEC-1..Q-SPEC-11 (ops-lead-standin, recorded gate actions).
- Safety classification (STD-REQ-6): **safety-critical** (IEC 61508-3 context). The change alters which tie switches FLISR commands closed. Every unit derived from this specification inherits the classification. `backend/app/flisr.py` is a protected path: two human reviewers (STD-GOV-6, STD-SAFETY-1).
- Scope (Q-SPEC-8): `build_plan` in `backend/app/flisr.py`; `POST /flisr/plan` in `backend/app/api.py`; new types in `backend/app/models.py`.

### Current behaviour (baseline, `main` @ 5f6b471, re-measured this attempt)

- `build_plan(feeder, lockout_switch_mrid, tie_capacity_kw: dict[str, float] | None)`. A tie with no entry reads as `0.0` kW (`flisr.py:98`, `tie_capacity_kw.get(switch.mrid, 0.0)`): an implicit "treat as zero", forbidden by STD-REQ-3.
- A tie is skipped when `transferred > available` (strict), so equality closes; there is no tolerance.
- Shipped model, `CB-1201` open: isolation opens `SEC-SW-1201-1` and `REC-1201-2`; restoration re-closes `CB-1201`. Tie `TIE-1201-1405` has L = 1490 kW.
  - no capacity → tie skipped, note `"Hollow Creek tie to 1405 skipped: 1490 kW exceeds 0 kW available capacity"`, `customers_restored = 0`, `customers_remaining = 437`, `transferred_load_kw = 0.0`.
  - C = 1490.0 → tie closed, `customers_restored = 341`, `customers_remaining = 96`, `transferred_load_kw = 1490.0`, no notes.
  - C = 1489.9 → tie skipped (note says "exceeds 1490 kW", rounding hides the 0.1 kW).
- HTTP today (`FlisrRequest`, Pydantic lax mode, extra fields ignored): a JSON `NaN` capacity is accepted, a string `"2000"` is coerced to 2000.0, and an unknown body field is silently ignored. All three reach the planner.
- No timestamp, no quality, no machine-readable reason for a skipped tie.

### Definitions

- **Candidate tie**: a `Switch` with `kind == tie` and `scada_controllable == True` for which `_nodes_restored_by` returns a non-empty node set. Other ties are skipped silently, as today (§3).
- **L (transferred load)**: sum of `Section.load_kw` over sections whose `to_node` is in the candidate node set. Unit kW; range L ≥ 0.
- **C (tie capacity)**: `TieCapacity.kw` — the alternate feeder's spare capacity as delivered by the SCADA scan every 10 s, kW on the same basis as `load_kw`. No unit conversion, no per-unit base, not nameplate (Q-SPEC-1).
- **τ (tolerance)**: 0.5 kW, the only tolerance; no additional safety margin (Q-SPEC-1, Q-SPEC-4). Per-unit statement waived by Q-SPEC-4.
- **as_of**: the evaluation instant. The request's `as_of` (timezone-aware ISO-8601 UTC instant supplied by the caller); when absent, the server's UTC now (Q-SPEC-10).
- **age**: `as_of − TieCapacity.timestamp`, in seconds (Q-SPEC-10). Negative when the timestamp is ahead of as_of.
- **Usable capacity**: an entry that is present, valid (REQ-TIECAP-8), `quality == "GOOD"` and `age ≤ 20 s` (Q-SPEC-2).
- **Present** (HTTP body field): the key appears in the JSON body, whatever its value.

## 1. Requirements

| ID | Requirement (one testable statement) | Inputs → outputs | Missing / late / invalid behaviour | Verification (oracle) | Depends on open Q |
|---|---|---|---|---|---|
| REQ-TIECAP-1 | `backend/app/models.py` shall define a Pydantic model `TieCapacity` with fields `kw` (kW, same basis as `Section.load_kw`), `timestamp` and `quality: str`, all required, and shall reject unknown fields. Model validation shall not range-check `kw` or require a timezone on `timestamp`; those checks are the planner's (REQ-TIECAP-8) so that they yield per-tie `CAPACITY_INVALID` and not a request error. | — → type | A missing or unknown field fails model validation (→ HTTP 422, REQ-TIECAP-13). | Test: model validation unit tests; inspection of `models.py`. | Q-SPEC-13 (type of `timestamp` only) |
| REQ-TIECAP-2 | `flisr.build_plan` shall accept `tie_capacity: dict[str, TieCapacity] \| None` keyed by tie switch mRID, and `as_of: datetime \| None`. When `as_of` is None it shall use the UTC now read once at the start of the call. | feeder, lockout mRID, tie_capacity, as_of → `RestorationPlan` | `tie_capacity` None or `{}` → every candidate tie is CAPACITY_UNKNOWN (REQ-TIECAP-5). Invalid `as_of` → open (Q-SPEC-12). | Test with an injected `as_of`; inspection. | Q-SPEC-12 (invalid as_of only) |
| REQ-TIECAP-3 | For a candidate tie with usable capacity C, `build_plan` shall emit a `close` restoration step for that tie **if and only if** `L ≤ C + 0.5 kW`. | L, C → close step present / absent | C not usable → REQ-TIECAP-5..8; never closed. | Test against an independent closed-form oracle: QA computes L with its own BFS over the test topology (not `network.load_on_nodes` or `_nodes_restored_by`) and evaluates `L_oracle ≤ C + 0.5`. Shipped-model boundary (L = 1490 kW): C = 1490.0 closes; C = 1489.5 closes (L = C + τ); C = 1489.4 blocked CAPACITY_EXCEEDED. Tolerance 0.5 kW engineering units; per-unit waived (Q-SPEC-4). | — |
| REQ-TIECAP-4 | For a candidate tie with usable capacity and `L > C + 0.5 kW`, `build_plan` shall emit no step for that tie and shall record `BlockedTie(tie_id=<mRID>, reason=CAPACITY_EXCEEDED)`. No partial pick-up (Q-SPEC-6). | L, C → blocked_ties entry | — | Test (oracle as REQ-TIECAP-3). | — |
| REQ-TIECAP-5 | For a candidate tie with no entry in `tie_capacity` (including None / `{}`), or whose entry has `quality != "GOOD"` (exact, case-sensitive match), `build_plan` shall emit no step for that tie and record `BlockedTie(reason=CAPACITY_UNKNOWN)`. A missing value shall never be read as 0 kW or any other value (Q-SPEC-2, Q-SPEC-9). | entry / quality → blocked_ties entry | Missing or non-GOOD → refuse for that tie only. | Test: missing key, `None`, `{}`, qualities `"BAD"`, `"SUSPECT"`, `"good"`, `""`. Inspection that no default capacity remains at `flisr.py:98`. | — |
| REQ-TIECAP-6 | For a candidate tie whose valid entry has `age > 20 s`, `build_plan` shall not use the value, emit no step for that tie and record `BlockedTie(reason=CAPACITY_STALE)`. `age ≤ 20 s` (exactly 20 s included) is fresh (Q-SPEC-2). | timestamp, as_of → usable / blocked | Late → refuse for that tie. | Test with injected as_of: age 19.999 s, 20.000 s (fresh), 20.001 s (stale). Oracle: closed-form `age > 20`. | — |
| REQ-TIECAP-7 | A timestamp ahead of as_of by no more than 2 s (−2 s ≤ age < 0) shall be treated as fresh; ahead by more than 2 s (age < −2 s) is CAPACITY_INVALID (Q-SPEC-10). | timestamp, as_of → usable / invalid | Future-dated → refuse for that tie. | Test: age −1.999 s, −2.000 s (fresh), −2.001 s (invalid). | — |
| REQ-TIECAP-8 | For a candidate tie whose entry has `kw` NaN, +inf, −inf, negative, or otherwise not a finite number, or a `timestamp` that is unparseable, timezone-naive, or more than 2 s ahead of as_of, `build_plan` shall emit no step for that tie and record `BlockedTie(reason=CAPACITY_INVALID)`. It shall never clamp or substitute a value (Q-SPEC-9, Q-SPEC-10). `kw = 0.0` and `kw = −0.0` are valid. | kw, timestamp → usable / blocked | Invalid → refuse for that tie. | Test: each listed class at `build_plan` level; NaN / ±Infinity also through HTTP (accepted as JSON numbers today, see baseline). | Q-SPEC-13 (unparseable timestamp through HTTP only) |
| REQ-TIECAP-9 | When several conditions apply to one tie, `build_plan` shall record only the first in the order CAPACITY_INVALID, CAPACITY_UNKNOWN, CAPACITY_STALE, CAPACITY_EXCEEDED (Q-SPEC-9). | entry → single reason | — | Test: every pair/combination of conditions, e.g. NaN + BAD + stale → INVALID; BAD + stale → UNKNOWN; stale + exceeded → STALE. Oracle: closed-form precedence function in the QA test. | — |
| REQ-TIECAP-10 | A blocked tie shall not change the plan's isolation steps, the lockout re-close step, or how any other candidate tie is evaluated (per-tie blocking, Q-SPEC-5). | per-tie inputs → plan | — | Test: two-tie generated topology, one tie usable, one blocked; isolation and the other tie's step equal the plan built with the blocked tie's entry made usable-but-exceeded. | — |
| REQ-TIECAP-11 | `RestorationPlan` shall gain `blocked_ties: list[BlockedTie]`, `BlockedTie{tie_id: str, reason}`, reason ∈ {CAPACITY_UNKNOWN, CAPACITY_STALE, CAPACITY_INVALID, CAPACITY_EXCEEDED}, with exactly one entry per blocked candidate tie, in `feeder.switches` order, empty when none is blocked (Q-SPEC-5). | — → plan field | — | Test (schema + content); inspection of `models.py`. | — |
| REQ-TIECAP-12 | For each blocked tie, `RestorationPlan.notes` shall contain one operator-readable entry naming the tie (`Switch.name`) and the reason; for CAPACITY_EXCEEDED it shall also state L and C in kW to at least 0.1 kW resolution; for CAPACITY_STALE the age in seconds. | blocked tie → note | — | Test: content asserted per reason. | — |
| REQ-TIECAP-13 | `POST /flisr/plan` shall accept a body field `tie_capacity` (object: tie mRID → `TieCapacity`) and an optional `as_of`; it shall return HTTP 200 with the plan, including `blocked_ties`, when ties are blocked, never 409 for a blocked tie (Q-SPEC-5). It shall reject with HTTP 422, before the planner runs, a body with wrong JSON types (no string→number or bool→number coercion), missing required fields or unknown fields at body or `TieCapacity` level (Q-SPEC-9). Existing 404 (unknown feeder) and 409 (`FlisrError`) are unchanged. | HTTP body → status + plan | Malformed → 422. | Test (FastAPI `TestClient`): `"kw": "2000"` → 422; extra body field → 422; `TieCapacity` missing `quality` → 422; one blocked tie → 200. | Q-SPEC-12 (as_of validation), Q-SPEC-13 (unparseable timestamp) |
| REQ-TIECAP-14 | The response body shall always carry `as_of`: the instant used — the supplied value, or the server's UTC now when absent (Q-SPEC-10). | as_of → echoed as_of | — | Test: supplied value echoed; absent → a UTC instant between the request's send and receive times. | — |
| REQ-TIECAP-15 | `tie_capacity` and the legacy `tie_capacity_kw` shall be mutually exclusive: both present in one body → HTTP 422 (Q-SPEC-11); both passed to `build_plan` → `build_plan` raises and returns no plan. | body → 422 / raise | — | Test: both present (including both `{}`) → 422; `build_plan` with both → raises. | — |
| REQ-TIECAP-16 | For one release, a request carrying only `tie_capacity_kw` (`dict[str, float]`) — and `build_plan` called with only `tie_capacity_kw` — shall be evaluated as `TieCapacity(kw=value, timestamp=as_of, quality="GOOD")` per entry through REQ-TIECAP-3..12, and the response shall carry `deprecations: ["tie_capacity_kw"]` (Q-SPEC-3, Q-SPEC-11). Otherwise `deprecations` is `[]`. | legacy map → same decisions + deprecations | Tie missing from the legacy map → CAPACITY_UNKNOWN. Legacy NaN / ±inf / negative → CAPACITY_INVALID. Wrong JSON type → 422. | Test: legacy-only with C = 2000.0 gives the same steps and totals as `tie_capacity` with GOOD/as_of; `deprecations` asserted. | — |
| REQ-TIECAP-17 | The `POST /flisr/plan` OpenAPI description shall state that `tie_capacity_kw` is deprecated, is removed after one release, and is mutually exclusive with `tie_capacity` (Q-SPEC-11). The Document stage's docs page carries the same note. | — → OpenAPI text | — | Inspection: `app.openapi()` text for `/flisr/plan`. | — |
| REQ-TIECAP-18 | For each blocked tie, `build_plan` shall add the customers of its candidate sections to `customers_remaining` and add nothing to `customers_restored` or `transferred_load_kw`. Closed-tie accounting is unchanged. | plan totals | — | Test; oracle: independent sums over the test topology. | — |
| REQ-TIECAP-19 | When no fault indication is present (`faulted_section is None`), the plan shall be as today (no isolation, no restoration, manual-patrol note) with `blocked_ties` empty. | — | — | Test (characterization). | — |
| REQ-TIECAP-20 | as_of shall be fixed once per `build_plan` call; every entry in one plan is aged against the same instant. | — | — | Test and inspection (no clock read inside the per-tie loop). | — |
| REQ-TIECAP-21 | Safety invariant: no plan shall contain a `close` step for a tie unless that tie's capacity is usable and `L ≤ C + 0.5 kW`; every candidate tie not closed shall appear exactly once in `blocked_ties` with the reason the REQ-TIECAP-9 precedence gives. | generated feeders + capacity maps + as_of → plans | Covers missing, non-GOOD, stale, boundary-age, future-dated, naive, non-finite, negative, below / at / above `L + τ`. | Test (STD-SAFETY-5): ≥ 500 seeded `random` cases over radial and branched topologies with one or more ties (the seeded generator in `backend/tests/rca_def_flisr_7_sweep.py` on branch `agent/rca-backfeed/explore` may be reused). Oracle: the QA-owned BFS of REQ-TIECAP-3 plus closed-form usability and precedence checks. | — |
| REQ-TIECAP-22 | For inputs where every candidate tie has usable capacity and `L ≤ C` or `L > C + 0.5 kW`, the isolation steps, restoration steps and their order, `customers_restored`, `customers_remaining` and `transferred_load_kw` shall equal `main` @ 5f6b471. | — | — | Test: `@pytest.mark.characterization` tests pinned on unmodified code before any change (STD-SAFETY-2). | — |

### Intended behaviour changes (blast radius)

1. A candidate tie with no capacity entry was skipped with a "0 kW available" note; it is now blocked CAPACITY_UNKNOWN. Steps and accounting are identical; note text and `blocked_ties` are new.
2. `C < L ≤ C + 0.5 kW` used to skip the tie and now closes it (Q-SPEC-1/Q-SPEC-4). This is the **only** change that makes the planner more permissive; reviewers should confirm it.
3. Legacy NaN / ±inf / negative values were compared numerically. `L > NaN` is False, so on the shipped model a NaN capacity **closes** `TIE-1201-1405` today, and so does +inf (re-measured this attempt). Both are now CAPACITY_INVALID, which removes a latent unsafe close.
4. HTTP: string→number coercion and unknown fields, accepted today, become 422. Clients that relied on them break.
5. Response schema gains `blocked_ties`, `as_of`, `deprecations` (additive).

## 2. Open questions (STD-REQ-4) — not resolved by assumption

- **Q-SPEC-12 — invalid `as_of`.** Q-SPEC-10 says `as_of` is a timezone-aware ISO-8601 UTC instant and covers only its absence. What happens when the supplied `as_of` is (a) timezone-naive, (b) aware with a non-UTC offset (e.g. `+02:00` — accept as the same instant, or reject?), (c) unparseable? Options: reject the request with 422 (no plan, not even isolation), or build the plan with isolation and block every candidate tie CAPACITY_INVALID (consistent with Q-SPEC-5 per-tie blocking). (d) Should a supplied `as_of` be bounded against the server clock? Without a bound a caller can make 10-minute-old capacity look fresh by back-dating `as_of`, which bypasses REQ-TIECAP-6. Blocks: REQ-TIECAP-2 (invalid as_of only), REQ-TIECAP-13 (as_of validation).
- **Q-SPEC-13 — unparseable capacity timestamp over HTTP.** Q-SPEC-9 says an unparseable timestamp is CAPACITY_INVALID (per tie, HTTP 200), and that wrong types are 422 (whole request). Over JSON a timestamp is a string either way. Is a string that is not ISO-8601 (e.g. `"yesterday"`) (a) a per-tie CAPACITY_INVALID with HTTP 200 — which means `TieCapacity.timestamp` must accept arbitrary strings and the planner parses them — or (b) a 422, leaving CAPACITY_INVALID-unparseable reachable only from Python callers? Also, is a JSON number (Unix seconds) a wrong type (422) or accepted? Blocks: REQ-TIECAP-1 (timestamp type), REQ-TIECAP-8 (HTTP path only), REQ-TIECAP-13.

## 3. Scope exclusions (STD-REQ-7)

- SCADA adapter and telemetry ingestion: scan scheduling, quality mapping, timestamping (integration team, Q-SPEC-3).
- Spare capacity of one alternate feeder shared by several ties (Q-SPEC-7); each tie is checked independently.
- Partial pick-up or load shedding to fit within capacity (Q-SPEC-6).
- Nameplate / thermal rating of the tie switch, unit conversion, per-unit bases, any safety margin beyond τ (Q-SPEC-1, Q-SPEC-4).
- Removing legacy `tie_capacity_kw` (separate change after one release, Q-SPEC-11).
- `tie_capacity` entries whose key is not a candidate tie of the feeder: ignored as today; not validated, not listed.
- `locate_fault` / fault-location logic; `_isolation_switches` and DEF-FLISR-7 (a tie that is an isolation point back-feeds the faulted section) — separate defect run. This change shall neither fix nor mask DEF-FLISR-7.
- Non-SCADA-controllable ties and ties with an empty candidate set: skipped silently as today, not in `blocked_ties`.
- `console/**` (does not call `/flisr/plan`), `state_estimator.py`, `agc.py`, `savecase.py`, `firmware/**`, `legacy/**`.

## 4. Verification notes for QA

- Independent oracle: QA-owned BFS over the test topology plus closed-form `L ≤ C + 0.5`, `age > 20`, `age < −2`, `quality == "GOOD"`, `math.isfinite(kw) and kw ≥ 0`, and the REQ-TIECAP-9 precedence. It must not import `app.network` or `app.flisr` helpers.
- Tolerance 0.5 kW engineering units; per-unit tolerance waived by Q-SPEC-4 — record the waiver against STD-SAFETY-6.
- Order of work (`.agents/skills/safety-critical-change/SKILL.md`): baseline → characterization (REQ-TIECAP-19, REQ-TIECAP-22) → failing reproductions (missing capacity read as 0 kW with no machine-readable reason; legacy NaN closes the tie) → minimal fix → invariant (REQ-TIECAP-21, ≥ 500 seeded cases).
- Tool classification (STD-SAFETY-7) is the assessor's finding; this specification claims no tool-certification credit.

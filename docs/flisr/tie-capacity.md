# FLISR restoration: tie switches close only within live spare capacity (REQ-TIECAP-1..23)

Audience: control-room operators and integrators who call `POST /flisr/plan` or
`app.flisr.build_plan`. This page describes the behaviour of the integrated
feature-tie-capacity change (branch `agent/feature-tie-capacity/integration`, built on the
DEF-FLISR-7 guard of `agent/rca-backfeed/fix`). Safety classification: safety-critical;
`backend/app/flisr.py` needs two human reviewers before merge.

Specification and design: `docs/specs/feature-tie-capacity/specification.md` and
`design.md` on branch `agent/feature-tie-capacity/design`.

## What changed

Before this change, a tie with no capacity value was read as 0 kW, `NaN` or `+inf` capacity
closed the tie (`L > NaN` is false), and a skipped tie had only a free-text note.

Now, for every SCADA-controllable tie switch that would pick up load after isolation (a
*candidate tie*), the planner closes the tie **only if** all of the following hold
(REQ-TIECAP-3, REQ-TIECAP-21):

1. the tie would not back-feed the faulted section (DEF-FLISR-7 guard, unchanged);
2. a capacity value for the tie is present, valid, quality `GOOD` and fresh (REQ-TIECAP-5..8);
3. the load to transfer `L` is at most the capacity `C` plus a 0.5 kW tolerance:
   `L <= C + 0.5 kW` (REQ-TIECAP-3). Equality closes; there is no other safety margin.

Every candidate tie that is not closed is listed once in `RestorationPlan.blocked_ties`
with one machine-readable reason, and gets one operator note in `notes` (REQ-TIECAP-11,
REQ-TIECAP-12). A blocked tie does not change the isolation steps, the lockout re-close or
any other tie's decision (REQ-TIECAP-10). Blocked ties are a normal plan: **HTTP 200, not
409** (REQ-TIECAP-13).

`C` is the alternate feeder's **spare** capacity as delivered by the SCADA scan every 10 s,
in kW on the same basis as `Section.load_kw`. It is not the switch nameplate rating, and no
unit conversion or per-unit base is applied (REQ-TIECAP-1, REQ-TIECAP-3).

### Block reasons and precedence

When several reasons apply to one tie, only the first in this order is reported
(REQ-TIECAP-9; the order is the declaration order of `TieBlockReason` in
`backend/app/models.py`):

| Reason | When | Operator note (from `_blocked_note`, measured on FDR-1201) | Requirement |
|---|---|---|---|
| `FAULTED_SECTION` | the tie's pick-up set touches either end of the faulted section | `Hollow Creek tie to 1405 (TIE-1201-1405) held open: would back-feed faulted section Hollow Creek tail (SEC-1201-04)` | DEF-FLISR-7, REQ-TIECAP-9, REQ-TIECAP-21 |
| `CAPACITY_INVALID` | `kw` is NaN, +inf, -inf or negative; or the timestamp is more than 2 s ahead of `as_of` | `... blocked (CAPACITY_INVALID): capacity nan kW is not a finite non-negative number` / `... capacity timestamp is 2.001 s ahead of as_of (limit 2 s)` | REQ-TIECAP-7, REQ-TIECAP-8 |
| `CAPACITY_UNKNOWN` | no entry for the tie (including no map or `{}`), or `quality` is not exactly `GOOD` (case-sensitive) | `... blocked (CAPACITY_UNKNOWN): no capacity value` / `... capacity quality 'BAD' is not GOOD` | REQ-TIECAP-5 |
| `CAPACITY_STALE` | age `as_of - timestamp` is more than 20 s | `... blocked (CAPACITY_STALE): capacity value is 20.001 s old (limit 20 s)` | REQ-TIECAP-6 |
| `CAPACITY_EXCEEDED` | usable capacity but `L > C + 0.5 kW` | `... blocked (CAPACITY_EXCEEDED): 1490.0 kW to transfer exceeds 1489.4 kW available capacity (+0.5 kW tolerance)` | REQ-TIECAP-4, REQ-TIECAP-12 |

`...` stands for `Hollow Creek tie to 1405` (the tie's `Switch.name`).

### Plan accounting for a blocked tie (REQ-TIECAP-18)

| Plan field | Effect |
|---|---|
| `restoration` | no `close` step for that tie |
| `customers_restored`, `transferred_load_kw` | nothing added for that tie |
| `customers_remaining` | capacity reasons: the customers of the tie's pick-up sections are added. `FAULTED_SECTION`: the same, except the faulted section, which is already counted once |

### New response fields

| Field | Meaning | Requirement |
|---|---|---|
| `blocked_ties` | `[{"tie_id": <tie mRID>, "reason": <TieBlockReason>}]` in `feeder.switches` order; `[]` when none | REQ-TIECAP-11 |
| `as_of` | the instant every capacity value was aged against, always UTC (`...Z`) | REQ-TIECAP-14 |
| `deprecations` | `["tie_capacity_kw"]` when the legacy field was used, else `[]` | REQ-TIECAP-16 |

## Request: `POST /flisr/plan`

```json
{
  "feeder_mrid": "FDR-1201",
  "lockout_switch_mrid": "CB-1201",
  "as_of": "2026-10-16T02:00:00Z",
  "tie_capacity": {
    "TIE-1201-1405": {"kw": 2000.0, "timestamp": "2026-10-16T01:59:55Z", "quality": "GOOD"}
  }
}
```

- `tie_capacity`: tie mRID → `{kw, timestamp, quality}` (REQ-TIECAP-1, REQ-TIECAP-13).
  Entries for mRIDs that are not candidate ties are ignored.
- `as_of` (optional): the evaluation instant, a timezone-aware ISO-8601 datetime. A non-UTC
  offset is accepted and normalised (`2026-10-16T04:00:00+02:00` is echoed as
  `2026-10-16T02:00:00Z`). When absent, the server clock is used and echoed
  (REQ-TIECAP-2, REQ-TIECAP-14). It must be no more than 60 s before and no more than 2 s
  after the server clock (REQ-TIECAP-23).
- The server clock is read once per request; every tie in one plan is aged against the same
  `as_of` (REQ-TIECAP-20).

### Deprecated: `tie_capacity_kw`

`tie_capacity_kw` (tie mRID → kW number) is **deprecated and will be removed one release
after this one** (REQ-TIECAP-16, REQ-TIECAP-17). Until then each value is evaluated as
`{kw: value, timestamp: as_of, quality: "GOOD"}` through the same rules, so a legacy NaN,
inf or negative value is `CAPACITY_INVALID` and a tie missing from the map is
`CAPACITY_UNKNOWN`. The response then carries `deprecations: ["tie_capacity_kw"]`.
`tie_capacity` and `tie_capacity_kw` are mutually exclusive: sending both (even both `{}`)
is HTTP 422; passing both to `build_plan` raises `ValueError` (REQ-TIECAP-15). The same
note is in the endpoint's OpenAPI description (`api._flisr_plan_description`).

## Behaviour for missing, boundary and invalid input

Measured on the shipped model with `CB-1201` open (fault located on `SEC-1201-03`; tie
`TIE-1201-1405` picks up L = 1490.0 kW and 341 customers; `as_of` fixed). Every row is pinned
by the tests named.

| Case | Input | Result | Requirement | Test |
|---|---|---|---|---|
| Capacity boundary | C = 1490.0 / 1489.5 / 1489.4 kW | close (341 restored, 96 remaining, 1490.0 kW) / close (`L = C + 0.5`) / `CAPACITY_EXCEEDED` (0 / 437 / 0.0) | REQ-TIECAP-3, REQ-TIECAP-4 | `backend/tests/test_flisr_tie_capacity_planner.py::test_req_tiecap_3_4_shipped_boundaries_against_oracle` |
| Zero capacity | C = 0.0 or -0.0 | valid value; `CAPACITY_EXCEEDED` for L = 1490 kW | REQ-TIECAP-8 | `backend/tests/test_flisr_tie_capacity_planner.py::test_req_tiecap_8_zero_capacity_is_valid` |
| Missing capacity | no map, `{}`, or tie not in the map | `CAPACITY_UNKNOWN`; never read as 0 kW | REQ-TIECAP-5 | `backend/tests/test_flisr_tie_capacity_planner.py::test_req_tiecap_5_missing_capacity_is_unknown`, `backend/tests/test_flisr_tie_capacity_repro.py::test_req_tiecap_5_repro_missing_capacity_blocks_tie_as_unknown` |
| Quality | `"BAD"`, `"SUSPECT"`, `"good"`, `""` | `CAPACITY_UNKNOWN` | REQ-TIECAP-5 | `backend/tests/test_flisr_tie_capacity_planner.py::test_req_tiecap_5_non_good_quality_is_unknown` |
| Age boundary | age 19.999 / 20.000 / 20.001 s | fresh / fresh / `CAPACITY_STALE` | REQ-TIECAP-6 | `backend/tests/test_flisr_tie_capacity_planner.py::test_req_tiecap_6_stale_boundary` |
| Future-dated boundary | timestamp ahead of `as_of` by 1.999 / 2.000 / 2.001 s | fresh / fresh / `CAPACITY_INVALID` | REQ-TIECAP-7 | `backend/tests/test_flisr_tie_capacity_planner.py::test_req_tiecap_7_future_dated_boundary` |
| Non-finite or negative capacity | `kw` NaN, +inf, -inf, -1.0 (JSON `NaN`, `Infinity`, `-Infinity`, `-1` over HTTP) | `CAPACITY_INVALID`, HTTP 200; never clamped | REQ-TIECAP-8 | `backend/tests/test_flisr_tie_capacity_planner.py::test_req_tiecap_8_non_finite_or_negative_capacity_is_invalid`, `backend/tests/test_flisr_tie_capacity_api.py::test_req_tiecap_8_non_finite_or_negative_json_capacity_is_200_invalid` |
| Several reasons | NaN + BAD + stale / BAD + stale / stale + exceeded | `CAPACITY_INVALID` / `CAPACITY_UNKNOWN` / `CAPACITY_STALE` | REQ-TIECAP-9 | `backend/tests/test_flisr_tie_capacity_planner.py::test_req_tiecap_9_first_reason_in_precedence_order` |
| Tie would back-feed the fault | fault on `SEC-1201-04`, any capacity state (GOOD 2000, NaN, BAD, stale, 10 kW, missing) | `FAULTED_SECTION`, 0 restored / 341 remaining | DEF-FLISR-7, REQ-TIECAP-9 | `backend/tests/test_flisr_tie_capacity_planner.py::test_req_tiecap_9_held_tie_is_faulted_section_whatever_the_capacity`, `backend/tests/test_flisr_tie_capacity_api.py::test_req_tiecap_13_held_tie_is_200_faulted_section` |
| Invalid section load | a pick-up section's `load_kw` NaN, ±inf or negative (also a negative spur inside a positive total) | whole plan refused: `FlisrError`, HTTP 409, lockout stays open | REQ-TIECAP-3 (design precondition) | `backend/tests/test_flisr_tie_capacity_planner.py::test_req_tiecap_3_invalid_section_load_refuses_the_plan`, `backend/tests/test_flisr_tie_capacity_planner.py::test_req_tiecap_3_negative_spur_inside_positive_total_refuses_the_plan`, `backend/tests/test_flisr_tie_capacity_api.py::test_req_tiecap_13_invalid_section_load_is_409_without_a_plan` |
| `as_of` bound | 60.000 s before / 60.001 s before / 2.000 s after / 2.001 s after server clock | 200 / 422 / 200 / 422 | REQ-TIECAP-23 | `backend/tests/test_flisr_tie_capacity_api.py::test_req_tiecap_23_as_of_bound_against_oracle` |
| `as_of` malformed | naive, `"yesterday"`, JSON number, `null` | 422 over HTTP; `build_plan` with a naive or non-datetime `as_of` raises `ValueError` | REQ-TIECAP-2, REQ-TIECAP-23 | `backend/tests/test_flisr_tie_capacity_api.py::test_req_tiecap_13_malformed_body_is_422_and_planner_not_called`, `backend/tests/test_flisr_tie_capacity_planner.py::test_req_tiecap_2_naive_or_non_datetime_as_of_raises` |
| Malformed body | `"kw": "2000"` or `true`; timestamp `"yesterday"`, `1790000000` or naive; `TieCapacity` missing `quality`; unknown field at body or `TieCapacity` level; `"tie_capacity": null`; both maps | 422 before the planner runs, no plan; the 422 body does not echo the rejected input | REQ-TIECAP-1, REQ-TIECAP-13, REQ-TIECAP-15 | `backend/tests/test_flisr_tie_capacity_api.py::test_req_tiecap_13_malformed_body_is_422_and_planner_not_called`, `backend/tests/test_flisr_tie_capacity_api.py::test_req_tiecap_13_rejected_body_with_non_finite_input_is_422_not_500`, `backend/tests/test_flisr_tie_capacity_models.py::test_req_tiecap_1_tie_capacity_rejects_http_422` |
| Legacy map | `tie_capacity_kw` only, C = 2000.0 | same steps and totals as `tie_capacity` GOOD at `as_of`, plus `deprecations` | REQ-TIECAP-16 | `backend/tests/test_flisr_tie_capacity_api.py::test_req_tiecap_16_legacy_only_matches_good_entry_and_is_flagged`, `backend/tests/test_flisr_tie_capacity_planner.py::test_req_tiecap_16_legacy_missing_or_invalid_values` |
| No fault indication (unchanged) | no `fault_indicator` set | no isolation or restoration; note `no fault indication received; manual patrol required`; `blocked_ties` `[]` | REQ-TIECAP-19 | `backend/tests/test_flisr_tie_capacity_characterization.py` |
| Unchanged errors | unknown feeder; lockout switch not open | 404; `FlisrError` / 409 | REQ-TIECAP-13 | `backend/tests/test_flisr_tie_capacity_api.py::test_req_tiecap_13_unknown_feeder_is_still_404` |

Behaviour that is **unchanged** on inputs that were already handled (usable capacity with
`L <= C` or `L > C + 0.5 kW`): isolation steps, restoration steps and their order and all
totals equal the base (REQ-TIECAP-22, `backend/tests/test_flisr_tie_capacity_characterization.py`).

Safety invariant (REQ-TIECAP-21): *no plan contains a `close` step for a tie unless its
capacity is usable and `L <= C + 0.5 kW`, and every candidate tie not closed appears exactly
once in `blocked_ties` with the precedence reason.* It holds over 1000 seeded radial and
branched feeders (seed `20261016`) against an independent oracle
(`backend/tests/test_flisr_tie_capacity_invariant.py::test_req_tiecap_21_no_tie_closed_without_usable_capacity_over_seeded_feeders`).

## Settings, units and defaults

Generated from the Pydantic models and `models.py` constants, not typed by hand.
`FlisrRequest` is defined in `backend/app/api.py` (the request body model is not in
`models.py`); everything else is in `backend/app/models.py`. Only the fields this change
adds or reads are listed.

| Field | Type | Default | Source |
|---|---|---|---|
| `FlisrRequest.feeder_mrid` | `StrictStr` | `required` | `backend/app/api.py` |
| `FlisrRequest.lockout_switch_mrid` | `StrictStr` | `required` | `backend/app/api.py` |
| `FlisrRequest.tie_capacity` | `dict[str, TieCapacity] \| None` | `None` | `backend/app/api.py` |
| `FlisrRequest.tie_capacity_kw` | `dict[str, StrictFloat] \| None` | `None` | `backend/app/api.py` |
| `FlisrRequest.as_of` | `IsoAwareDatetime \| None` | `None` | `backend/app/api.py` |
| `TieCapacity.kw` | `StrictFloat` | `required` | `backend/app/models.py` |
| `TieCapacity.timestamp` | `IsoAwareDatetime` | `required` | `backend/app/models.py` |
| `TieCapacity.quality` | `StrictStr` | `required` | `backend/app/models.py` |
| `BlockedTie.tie_id` | `str` | `required` | `backend/app/models.py` |
| `BlockedTie.reason` | `TieBlockReason` | `required` | `backend/app/models.py` |
| `RestorationPlan.feeder_mrid` | `str` | `required` | `backend/app/models.py` |
| `RestorationPlan.faulted_section` | `str \| None` | `required` | `backend/app/models.py` |
| `RestorationPlan.isolation` | `list[IsolationStep]` | `[]` | `backend/app/models.py` |
| `RestorationPlan.restoration` | `list[IsolationStep]` | `[]` | `backend/app/models.py` |
| `RestorationPlan.customers_restored` | `int` | `0` | `backend/app/models.py` |
| `RestorationPlan.customers_remaining` | `int` | `0` | `backend/app/models.py` |
| `RestorationPlan.transferred_load_kw` | `float` | `0.0` | `backend/app/models.py` |
| `RestorationPlan.notes` | `list[str]` | `[]` | `backend/app/models.py` |
| `RestorationPlan.as_of` | `AwareDatetime` | `required` | `backend/app/models.py` |
| `RestorationPlan.blocked_ties` | `list[BlockedTie]` | `[]` | `backend/app/models.py` |
| `RestorationPlan.deprecations` | `list[str]` | `[]` | `backend/app/models.py` |
| `Section.customers` | `int` | `0` | `backend/app/models.py` |
| `Section.load_kw` | `float` | `0.0` | `backend/app/models.py` |

| Constant | Value | Source |
|---|---|---|
| `TIE_CAPACITY_TOLERANCE_KW` | 0.5 kW | `backend/app/models.py` |
| `TIE_CAPACITY_MAX_AGE` | 20 s | `backend/app/models.py` |
| `TIE_CAPACITY_MAX_LEAD` | 2 s | `backend/app/models.py` |
| `AS_OF_MAX_LAG` | 60 s | `backend/app/models.py` |
| `AS_OF_MAX_LEAD` | 2 s | `backend/app/models.py` |
| `TIE_CAPACITY_GOOD_QUALITY` | 'GOOD' | `backend/app/models.py` |

`TieBlockReason` members, in reporting precedence order: `FAULTED_SECTION`, `CAPACITY_INVALID`, `CAPACITY_UNKNOWN`, `CAPACITY_STALE`, `CAPACITY_EXCEEDED`.

Units: `kw`, `Section.load_kw` and `transferred_load_kw` are kW; customer fields are counts;
time limits are seconds. The models declare **no numeric range** for `TieCapacity.kw` or
`Section.load_kw` on purpose: range checks are made by the planner (`CAPACITY_INVALID` for
capacity, `FlisrError` for section load), so an invalid value is reported, not silently
rejected (REQ-TIECAP-1, REQ-TIECAP-8).

Regenerate both tables from the repo root:

```bash
PYTHONPATH=backend python - <<'EOF'
import re
from datetime import timedelta
from pydantic_core import PydanticUndefined
from app import api, models
spec = [(api.FlisrRequest, None, "backend/app/api.py"),
        (models.TieCapacity, None, "backend/app/models.py"),
        (models.BlockedTie, None, "backend/app/models.py"),
        (models.RestorationPlan, None, "backend/app/models.py"),
        (models.Section, ["load_kw", "customers"], "backend/app/models.py")]
print("| Field | Type | Default | Source |\n|---|---|---|---|")
for model, keep, src in spec:
    for name, f in model.model_fields.items():
        if keep and name not in keep:
            continue
        a = f.annotation
        t = a.__name__ if isinstance(a, type) else str(a).replace("typing.", "").replace("app.models.", "")
        t = re.sub(r"Optional\[Annotated\[pydantic\.types\.AwareDatetime, BeforeValidator.*", "IsoAwareDatetime | None", t)
        t = t.replace("Annotated[float, Strict(strict=True)]", "StrictFloat")
        meta = [type(m).__name__ for m in f.metadata]
        if "Strict" in meta:
            t = "Strict" + t.capitalize()
        if "BeforeValidator" in meta and t == "AwareDatetime":
            t = "IsoAwareDatetime"
        d = (repr(f.default) if f.default is not PydanticUndefined
             else repr(f.default_factory()) if f.default_factory else "required")
        print(f"| `{model.__name__}.{name}` | `{t.replace('|', chr(92) + '|')}` | `{d}` | `{src}` |")
print()
print("| Constant | Value | Source |\n|---|---|---|")
for name in ["TIE_CAPACITY_TOLERANCE_KW", "TIE_CAPACITY_MAX_AGE", "TIE_CAPACITY_MAX_LEAD",
             "AS_OF_MAX_LAG", "AS_OF_MAX_LEAD", "TIE_CAPACITY_GOOD_QUALITY"]:
    v = getattr(models, name)
    s = f"{v.total_seconds():g} s" if isinstance(v, timedelta) else (f"{v:g} kW" if isinstance(v, float) else repr(v))
    print(f"| `{name}` | {s} | `backend/app/models.py` |")
print()
print("`TieBlockReason` members, in reporting precedence order: " + ", ".join(f"`{m.value}`" for m in models.TieBlockReason) + ".")
EOF
```

## What this change does not do

- **No SCADA adapter work.** Scan scheduling, quality mapping and timestamping of capacity
  values belong to the integration team; the planner only judges what it is given.
- **No shared-capacity check.** Each tie is checked on its own. If two ties draw on the same
  alternate feeder, their combined pick-up is not compared with that feeder's spare capacity.
- **No partial pick-up or load shedding** to fit within capacity: a tie either closes for its
  whole pick-up set or is blocked.
- **No nameplate or thermal rating, unit conversion, per-unit base or safety margin** beyond
  the 0.5 kW tolerance.
- **Does not remove `tie_capacity_kw`.** Removal is a separate change after one release.
- **Does not validate or list** `tie_capacity` entries whose key is not a candidate tie, and
  does not list non-SCADA-controllable ties or ties with an empty pick-up set.
- **Does not change fault location** (`locate_fault`) or isolation (`_isolation_switches`),
  and does not change the DEF-FLISR-7 guard's decision.
- **Does not remove back-dating entirely.** An `as_of` up to 60 s before the server clock is
  accepted, so a capacity value up to 80 s older than the server clock can still count as
  fresh.
- **`customers_remaining` can over-count** when two ties pick up the same sections and one is
  blocked: the blocked tie's customers are added even if the other tie restored them.
- **Does not change the console** (`console/**` does not call `/flisr/plan`).

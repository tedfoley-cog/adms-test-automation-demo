# FLISR restoration: tie switches are held open onto a faulted section (DEF-FLISR-7)

Audience: control-room operators and integrators who call `POST /flisr/plan` or
`app.flisr.build_plan`. This page describes behaviour as of the integrated DEF-FLISR-7
change (`backend/app/flisr.py`, `build_plan` restoration loop, lines 97-107).

## What changed (DEF-FLISR-7)

Before this change, `build_plan` could close a tie switch onto the faulted section and
re-energise it from the alternate feeder. On FDR-1201 a fault on SEC-1201-04 (Hollow Creek
tail) with lockout on CB-1201 produced a plan that closed TIE-1201-1405 onto the fault
whenever the tie capacity was 1490 kW (that section's own load) or more.

Now, for every SCADA-controllable tie, the planner works out the tie's pick-up set (the
nodes the tie would energise after isolation, `_nodes_restored_by`). **If that set contains
either end of the faulted section (`from_node` or `to_node`), the tie is held open** — no
close step is issued. This check runs before the capacity check, so no tie capacity value
can override it. (DEF-FLISR-7)

When a tie is held open, the plan shows it as follows. (DEF-FLISR-7, accounting confirmed
in Q-REVIEW-2)

| Plan field | Effect of a held-open tie |
|---|---|
| `restoration` | no `close` step for that tie |
| `notes` | `"<tie name> (<tie mRID>) held open: would back-feed faulted section <section name> (<section mRID>)"` |
| `customers_restored` | nothing added for that tie |
| `transferred_load_kw` | nothing added for that tie |
| `customers_remaining` | the faulted section's customers are counted **once**; customers of any *other* (healthy) sections in the tie's pick-up set are added, because they stay off supply |

The fail-safe direction is to refuse the close and leave the decision to the operator. The
planner does not look for another way to re-route supply to the stranded load. (DEF-FLISR-7)

### Worked example: FDR-1201, fault on SEC-1201-04, lockout CB-1201

Request body `{"feeder_mrid": "FDR-1201", "lockout_switch_mrid": "CB-1201",
"tie_capacity_kw": {"TIE-1201-1405": 2000.0}}` returns:

| Field | Value |
|---|---|
| `faulted_section` | `SEC-1201-04` |
| `isolation` | `REC-1201-2 open` ("upstream isolation of Hollow Creek tail") |
| `restoration` | `CB-1201 close` only (TIE-1201-1405 is **not** closed) |
| `customers_restored` / `customers_remaining` | `0` / `341` |
| `transferred_load_kw` | `0.0` |
| `notes` | `Hollow Creek tie to 1405 (TIE-1201-1405) held open: would back-feed faulted section Hollow Creek tail (SEC-1201-04)` |

Before the fix the same request returned `TIE-1201-1405 close`, 341 restored / 341
remaining and 1490 kW transferred: the faulted section's own customers were counted as
both lost and restored.

Tests: `backend/tests/test_flisr_def_flisr_7.py::test_def_flisr_7_plan_holds_tie_open_and_counts_faulted_customers_once`,
`backend/tests/test_flisr_def_flisr_7_qa.py::test_qa_def_flisr_7_nominal_drill_14_stand_in`,
`backend/tests/test_flisr_def_flisr_7_qa.py::test_qa_def_flisr_7_api_plan_matches_direct_plan`.

## Behaviour for missing, boundary and invalid input

Every row below is pinned by a test. All of them cite DEF-FLISR-7.

| Case | Input | Result | Test |
|---|---|---|---|
| Boundary: capacity around the faulted section's load | `TIE-1201-1405` = 0, 1489, 1490, 1491, 1e12 kW, fault SEC-1201-04 | Tie held open for every value; plan identical to the worked example | `test_flisr_def_flisr_7_qa.py::test_qa_def_flisr_7_refusal_is_independent_of_tie_capacity` |
| Boundary: healthy tail (unchanged) | fault SEC-1201-03, capacity 1489 / 1490 / 1491 kW (pick-up load 1490 kW) | 1489 kW: tie skipped (0 restored / 437 remaining). 1490 and 1491 kW: tie closed (341 restored / 96 remaining). A tie closes when pick-up load ≤ capacity | `test_flisr_def_flisr_7_qa.py::test_qa_def_flisr_7_healthy_tail_capacity_boundary_unchanged` |
| Missing capacity, faulted tie | `tie_capacity_kw` omitted / `None` / `{}` / only an unrelated tie listed | Tie held open with the named note | `test_flisr_def_flisr_7_qa.py::test_qa_def_flisr_7_missing_capacity_still_refuses_with_named_note` |
| Missing capacity, healthy tie (unchanged) | fault SEC-1201-03, no capacity given | Missing capacity is treated as 0 kW: tie skipped, note `... skipped: 1490 kW exceeds 0 kW available capacity`. It never becomes an implicit close | `test_flisr_def_flisr_7_qa.py::test_qa_def_flisr_7_missing_capacity_on_healthy_tail_is_a_skip_not_a_close` |
| Invalid capacity, faulted tie | `NaN`, `+inf`, `-1.0` kW | Tie held open; the invalid value cannot bypass the guard | `test_flisr_def_flisr_7_qa.py::test_qa_def_flisr_7_invalid_capacity_cannot_bypass_the_guard` |
| Short capacity, faulted tie | 1000 kW, fault SEC-1201-04 | Held open (not "skipped"); faulted customers counted once: 0 / 341 / 0 kW | `test_flisr_def_flisr_7.py::test_def_flisr_7_short_tie_capacity_still_counts_faulted_customers_once` |
| Tie on any end of the faulted section | Extra tie on the faulted section's upstream or downstream node, even when a recloser or sectionalizer also bounds that end | Held open. A tie on a healthy node still closes | `test_flisr_def_flisr_7_qa.py::test_qa_def_flisr_7_tie_on_any_faulted_endpoint_is_refused` |
| Pick-up reaches the fault through a manual switch | Fault SEC-1201-03, REC-1201-2 not SCADA-controllable | Isolation is `SEC-SW-1201-1` only; TIE-1201-1405 held open; 0 restored / 437 (96 + 341) remaining | `test_flisr_def_flisr_7_qa.py::test_qa_def_flisr_7_pick_up_through_non_scada_downstream_switch_is_refused`, `test_flisr_def_flisr_7.py::test_def_flisr_7_tie_refused_when_pick_up_reaches_unisolated_faulted_section` |
| Non-SCADA tie (unchanged) | `scada_controllable = False` on the tie | Never a restoration candidate; no note | `test_flisr_def_flisr_7_qa.py::test_qa_def_flisr_7_non_scada_tie_is_never_a_candidate` |
| Error paths (unchanged) | Lockout switch not open; unknown switch mRID; no SCADA switch can isolate the section | `FlisrError` "... is not in lockout" (HTTP 409); `KeyError` "unknown switch" (HTTP 404 for an unknown feeder); `FlisrError` "no SCADA switch can isolate ..." (HTTP 409) | `test_flisr_def_flisr_7_qa.py::test_qa_def_flisr_7_error_paths_retained`, `test_flisr_def_flisr_7_qa.py::test_qa_def_flisr_7_api_plan_matches_direct_plan`, `test_flisr_characterization.py::test_def_flisr_7_char_refuses_when_lockout_switch_closed` |
| No fault indication (unchanged) | No section has `fault_indicator` set | No isolation or restoration; note "no fault indication received; manual patrol required" | `test_flisr_characterization.py::test_def_flisr_7_char_no_fault_indication_requires_patrol` |

Safety invariant: *a de-energised faulted section is never back-fed during restoration.* It
holds over 500 seeded radial and branched feeders
(`test_flisr_def_flisr_7.py::test_def_flisr_7_invariant_faulted_section_never_back_fed_over_seeded_feeders`)
and over 600 more seeded feeders, checked against an independent reference model
(`test_flisr_def_flisr_7_qa.py::test_qa_def_flisr_7_seeded_plans_agree_with_oracle_and_never_back_feed`).
(DEF-FLISR-7)

## Inputs, units and defaults

This table is generated from the Pydantic models, not typed by hand. `FlisrRequest` is
defined in `backend/app/api.py`; the other models are in `backend/app/models.py`. Only the
fields FLISR planning reads are listed. The DEF-FLISR-7 change did not modify either module.

| Field | Type | Default | Source |
|---|---|---|---|
| `FlisrRequest.feeder_mrid` | `str` | `required` | `backend/app/api.py` `FlisrRequest` |
| `FlisrRequest.lockout_switch_mrid` | `str` | `required` | `backend/app/api.py` `FlisrRequest` |
| `FlisrRequest.tie_capacity_kw` | `dict[str, float]` | `{}` | `backend/app/api.py` `FlisrRequest` |
| `Switch.kind` | `SwitchKind` | `required` | `backend/app/models.py` `Switch` |
| `Switch.open` | `bool` | `False` | `backend/app/models.py` `Switch` |
| `Switch.scada_controllable` | `bool` | `True` | `backend/app/models.py` `Switch` |
| `Switch.from_node` | `str` | `required` | `backend/app/models.py` `Switch` |
| `Switch.to_node` | `str` | `required` | `backend/app/models.py` `Switch` |
| `Section.from_node` | `str` | `required` | `backend/app/models.py` `Section` |
| `Section.to_node` | `str` | `required` | `backend/app/models.py` `Section` |
| `Section.customers` | `int` | `0` | `backend/app/models.py` `Section` |
| `Section.load_kw` | `float` | `0.0` | `backend/app/models.py` `Section` |
| `RestorationPlan.feeder_mrid` | `str` | `required` | `backend/app/models.py` `RestorationPlan` |
| `RestorationPlan.faulted_section` | `str \| None` | `required` | `backend/app/models.py` `RestorationPlan` |
| `RestorationPlan.isolation` | `list[app.models.IsolationStep]` | `[]` | `backend/app/models.py` `RestorationPlan` |
| `RestorationPlan.restoration` | `list[app.models.IsolationStep]` | `[]` | `backend/app/models.py` `RestorationPlan` |
| `RestorationPlan.customers_restored` | `int` | `0` | `backend/app/models.py` `RestorationPlan` |
| `RestorationPlan.customers_remaining` | `int` | `0` | `backend/app/models.py` `RestorationPlan` |
| `RestorationPlan.transferred_load_kw` | `float` | `0.0` | `backend/app/models.py` `RestorationPlan` |
| `RestorationPlan.notes` | `list[str]` | `[]` | `backend/app/models.py` `RestorationPlan` |

`SwitchKind` values: `breaker`, `recloser`, `sectionalizer`, `tie`. Only `tie` switches with
`scada_controllable = True` are restoration candidates.

Units: tie capacity, `Section.load_kw` and `transferred_load_kw` are in kW. `customers` and
the customer totals are customer counts. The models declare **no ranges** for any of these
fields. A tie mRID missing from `tie_capacity_kw` is treated as 0 kW
(`backend/app/flisr.py:109`, `tie_capacity_kw.get(switch.mrid, 0.0)`).

Regenerate the table from the repo root:

```bash
PYTHONPATH=backend python - <<'PY'
from pydantic_core import PydanticUndefined
from app import api, models
spec = [(api.FlisrRequest, None, "backend/app/api.py"),
        (models.Switch, ["kind", "open", "scada_controllable", "from_node", "to_node"], "backend/app/models.py"),
        (models.Section, ["from_node", "to_node", "customers", "load_kw"], "backend/app/models.py"),
        (models.RestorationPlan, None, "backend/app/models.py")]
print("| Field | Type | Default | Source |\n|---|---|---|---|")
for model, keep, src in spec:
    for name, f in model.model_fields.items():
        if keep and name not in keep:
            continue
        a = f.annotation
        t = a.__name__ if isinstance(a, type) else str(a).replace("typing.", "")
        d = (repr(f.default) if f.default is not PydanticUndefined
             else repr(f.default_factory()) if f.default_factory else "required")
        print(f"| `{model.__name__}.{name}` | `{t.replace('|', chr(92) + '|')}` | `{d}` | `{src}` `{model.__name__}` |")
PY
```

## What this change does not do

- **It does not check that the alternate feeder is healthy** before closing a tie onto
  *healthy* sections. A separate defect is being filed for this (Q-REVIEW-1).
- **It does not validate tie capacity values.** The guard ignores capacity, so invalid values
  cannot close a tie onto the faulted section. For a tie whose pick-up set is all healthy,
  capacity handling is unchanged: `NaN` or `+inf` lets the tie close (the check is
  `pick-up load > capacity`, which is false for both), and a negative value causes a skip.
  Through `POST /flisr/plan`, a JSON `NaN` is accepted and a non-numeric string is rejected
  with HTTP 422.
- **It does not change isolation.** `_isolation_switches` still skips tie switches and does
  not list them as isolation steps; the tie is held open by the restoration guard and
  reported in `notes`.
- **It does not stop the lockout reclose from re-energising an unisolated fault.** If the
  switch upstream of the faulted section is not SCADA-controllable, the lockout switch is
  still closed and can energise the fault from the feeder source. This is a separate,
  unfixed issue.
- **It does not fix `customers_remaining` across several ties.** The figure is added per tie,
  so a healthy section in the pick-up set of more than one refused or skipped tie can be
  counted more than once. This is a separate, unfixed issue.
- **It does not re-route stranded load.** Healthy sections that are only reachable through a
  held-open tie stay off supply and are counted in `customers_remaining`.
- `locate_fault`, the capacity check, `network.py` and `models.py` are unchanged.

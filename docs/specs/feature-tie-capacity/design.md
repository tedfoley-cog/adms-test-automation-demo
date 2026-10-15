# Design — FLISR restoration respects tie-switch capacity

Run: `feature-tie-capacity` · Stage: DESIGN · Attempt: 1 · Inputs: `specification.md` (attempt 4, complete), `units.json` (U1–U4)
Safety classification: **safety-critical** (STD-SAFETY-1). Protected path `backend/app/flisr.py`: two human reviewers (STD-GOV-6).
Status: **BLOCKED on Q-DESIGN-1** (§9). Everything below is complete; only §6.3 depends on the answer.

Baseline re-measured on `main` @ 5f6b471: `pytest backend -q` → 2 passed; `ruff check backend tools` → 1 pre-existing error in `tools/` (UP017), unrelated to this change.

## 1. Components and layers

Layer map (repo contract): `ui → api → logic → models`. No lower layer imports an upper one (STD-ARCH-3).

| Layer | Module | Change | Imports (allowed) |
|---|---|---|---|
| models | `backend/app/models.py` | New: constants, `IsoAwareDatetime`, `TieCapacity`, `TieBlockReason`, `BlockedTie`. Extended: `RestorationPlan`. | pydantic, stdlib only |
| logic | `backend/app/flisr.py` | New: `tie_capacity_verdict()` (the single capacity characteristic), `_legacy_to_tie_capacity()`, `_blocked_note()`. Changed: `build_plan()` signature and tie loop. `locate_fault`, `_isolation_switches`, `_nodes_restored_by` unchanged. | `.models`, `.network` (same layer, as today) |
| logic | `backend/app/network.py` | Unchanged (`load_on_nodes` keeps computing L). | `.models` |
| api | `backend/app/api.py` | Changed: `FlisrRequest`, `flisr_plan` route; new `server_now()` dependency, `_check_as_of_bound()`. | `.flisr`, `.models`, `.network` |
| ui | `console/**` | Unchanged (does not call `/flisr/plan`). | — |

Data flow (HTTP): JSON body → FastAPI/Pydantic request validation (`FlisrRequest`, `TieCapacity`) → `_check_as_of_bound(as_of, server_now)` → `flisr.build_plan(..., tie_capacity | tie_capacity_kw, as_of=resolved)` → per candidate tie `tie_capacity_verdict(entry, L, as_of)` → `RestorationPlan` (with `blocked_ties`, `as_of`, `deprecations`) → HTTP 200. Any validation failure → HTTP 422 and `build_plan` is never called.

## 2. Data models — `backend/app/models.py` (U2, extended in U3)

Models and constants only; no plant decision logic (STD-ARCH-1). The one validator function is a type parser (it decides whether an input *is* an ISO-8601 string), not a plant decision.

```python
# Tie-capacity characteristic parameters (single source; spec Q-SPEC-1/2/4/10/12)
TIE_CAPACITY_TOLERANCE_KW: Final = 0.5
TIE_CAPACITY_MAX_AGE = timedelta(seconds=20)        # age > 20 s  -> CAPACITY_STALE
TIE_CAPACITY_MAX_LEAD = timedelta(seconds=2)        # age < -2 s  -> CAPACITY_INVALID
AS_OF_MAX_LAG = timedelta(seconds=60)               # server_now - as_of > 60 s -> 422
AS_OF_MAX_LEAD = timedelta(seconds=2)               # as_of - server_now > 2 s  -> 422
TIE_CAPACITY_GOOD_QUALITY: Final = "GOOD"

def _require_iso_string(value):          # BeforeValidator
    datetime -> pass through (Python callers);
    str      -> datetime.fromisoformat(value)  (rejects "yesterday", "1790000000")
    other    -> ValueError  (JSON numbers, bool, null)
IsoAwareDatetime = Annotated[AwareDatetime, BeforeValidator(_require_iso_string)]

class TieCapacity(BaseModel):            # REQ-TIECAP-1
    model_config = ConfigDict(extra="forbid")
    kw: StrictFloat                      # JSON number only; NaN/±inf/negative pass (flagged by the planner)
    timestamp: IsoAwareDatetime          # aware ISO-8601 only; no clock comparison here
    quality: StrictStr

class TieBlockReason(StrEnum):           # REQ-TIECAP-11; declaration order == precedence (REQ-TIECAP-9)
    CAPACITY_INVALID, CAPACITY_UNKNOWN, CAPACITY_STALE, CAPACITY_EXCEEDED

class BlockedTie(BaseModel):
    tie_id: str
    reason: TieBlockReason

class RestorationPlan(BaseModel):        # existing fields unchanged
    ...
    as_of: AwareDatetime                 # U3, REQ-TIECAP-14: required, always UTC
    blocked_ties: list[BlockedTie] = []  # U2, REQ-TIECAP-11
    deprecations: list[str] = []         # U3, REQ-TIECAP-16
```

Why per-field strictness, not `ConfigDict(strict=True)`: measured on pydantic 2.14.1 / fastapi 0.143.1 (this stage, prototype outside the repo), FastAPI validates the body in Python mode, so model-wide strict rejects valid ISO strings (`datetime_type`), and lax `AwareDatetime` alone accepts the numeric string `"1790000000"` as a Unix time. `IsoAwareDatetime` measured: `"yesterday"`, `1790000000`, `"1790000000"`, `null`, naive and date-only → rejected; `Z`, `+02:00`, basic `20261015T220000Z` → accepted. `StrictFloat` measured: JSON `2000` → 2000.0 accepted; `"2000"`, `true`, `null` → rejected; JSON `NaN`/`-Infinity` reach the model. `extra="forbid"` → `extra_forbidden` 422.

`RestorationPlan.as_of` is required because REQ-TIECAP-14 says *always*; `flisr.build_plan` is the only constructor (grep: `flisr.py:76`). Characterization (U1) pins fields individually, so it is unaffected.

## 3. Shared characteristic — `flisr.tie_capacity_verdict` (STD-ARCH-2)

One implementation of the capacity decision, used by `build_plan` and by nothing else in production:

```python
def tie_capacity_verdict(
    entry: TieCapacity | None, transferred_kw: float, as_of: datetime
) -> TieBlockReason | None:
    """None = the tie may close. Otherwise the first applicable reason (REQ-TIECAP-9).
    Absent entry -> CAPACITY_UNKNOWN. Out-of-range kw (NaN, ±inf, < 0) or timestamp more than
    2 s ahead of as_of -> CAPACITY_INVALID. Non-GOOD quality -> CAPACITY_UNKNOWN. Older than
    20 s -> CAPACITY_STALE. Never substitutes or clamps a value."""
    if entry is None:                                          -> CAPACITY_UNKNOWN
    age = as_of - entry.timestamp                              # timedelta, exact µs
    if not (math.isfinite(entry.kw) and entry.kw >= 0.0) or age < -TIE_CAPACITY_MAX_LEAD:
                                                               -> CAPACITY_INVALID
    if entry.quality != TIE_CAPACITY_GOOD_QUALITY:             -> CAPACITY_UNKNOWN
    if age > TIE_CAPACITY_MAX_AGE:                             -> CAPACITY_STALE
    if transferred_kw <= entry.kw + TIE_CAPACITY_TOLERANCE_KW: -> None (close)
    return CAPACITY_EXCEEDED
```

Design decisions:
- **Positive close condition.** The tie closes only when `L <= C + τ` evaluates True. Any NaN that reaches the comparison (e.g. a NaN `Section.load_kw` in the model file) evaluates False and blocks. Today's `transferred > available` closes on NaN (spec intended change 3); this structure removes that failure mode rather than special-casing it (STD-SAFETY-4).
- **Ages compared as `timedelta`**, never as float seconds, so the 20.000 s / 20.001 s and −2.000 s / −2.001 s boundaries are exact at microsecond resolution (measured: `20.001 s > 20 s` True, `20 s > 20 s` False).
- `kw = -0.0` passes `>= 0.0` (valid, as the spec requires).
- Precedence is the order of the `if` statements; a missing entry can only be UNKNOWN.

## 4. Planner — `flisr.build_plan` (U3)

```python
def build_plan(
    feeder: Feeder,
    lockout_switch_mrid: str,
    tie_capacity_kw: dict[str, float] | None = None,     # legacy, deprecated (kept positional for callers)
    *,
    tie_capacity: dict[str, TieCapacity] | None = None,
    as_of: datetime | None = None,
) -> RestorationPlan:
```

Behaviour for absent / stale / out-of-range inputs (STD-ARCH-4), in docstring form:

| Input | Behaviour |
|---|---|
| both `tie_capacity` and `tie_capacity_kw` not None (incl. both `{}`) | `ValueError`; no plan (REQ-TIECAP-15) |
| `as_of` None | `datetime.now(UTC)` read **once** at entry (REQ-TIECAP-2, REQ-TIECAP-20) |
| `as_of` naive | `ValueError`; no plan (REQ-TIECAP-2) |
| `as_of` aware, any offset | `as_of.astimezone(UTC)`; same instant; stored in `plan.as_of` |
| `tie_capacity_kw` given (legacy) | each entry → `TieCapacity.model_construct(kw=float(v), timestamp=as_of, quality="GOOD")` (no re-validation, so NaN/±inf/negative survive and become CAPACITY_INVALID); `plan.deprecations = ["tie_capacity_kw"]` (REQ-TIECAP-16) |
| both None, or `{}` | every candidate tie CAPACITY_UNKNOWN (REQ-TIECAP-5) |
| entry for a non-candidate tie | ignored, as today (spec §3) |
| lockout not open / no isolating switch | `FlisrError`, unchanged |
| no fault indication | unchanged early return; `blocked_ties` stays `[]` (REQ-TIECAP-19) |

Why `ValueError` and not `FlisrError`: `FlisrError` means "the network state does not allow a defensible plan" and maps to HTTP 409. Naive `as_of` and both-maps are caller contract violations that HTTP validation already rejects with 422, so they never reach `build_plan` from `api.py`; a direct Python caller gets an exception and no plan either way.

Tie loop (replaces `flisr.py:92-121`; isolation, lockout re-close and `_nodes_restored_by` untouched, REQ-TIECAP-10):

```text
for switch in feeder.switches:                 # order => blocked_ties order (REQ-TIECAP-11)
    skip silently if not tie / not SCADA / empty candidate set     # as today
    L = load_on_nodes(feeder, candidate_nodes)
    customers = Σ customers of sections whose to_node ∈ candidate_nodes
    entry = capacities.get(switch.mrid)       # no default value — removes `.get(..., 0.0)` at flisr.py:98
    reason = tie_capacity_verdict(entry, L, as_of)
    if reason is None:
        append close step; transferred_load_kw += L; customers_restored += customers   # unchanged
    else:
        blocked_ties.append(BlockedTie(tie_id=switch.mrid, reason=reason))
        notes.append(_blocked_note(switch, reason, entry, L, as_of))
        customers_remaining += customers                                        # REQ-TIECAP-18
```

Operator notes (`_blocked_note`, REQ-TIECAP-12), one per blocked tie, naming `Switch.name` and the reason code:

| Reason | Note |
|---|---|
| CAPACITY_EXCEEDED | `"{name} blocked (CAPACITY_EXCEEDED): {L:.1f} kW to transfer exceeds {C:.1f} kW available capacity (+0.5 kW tolerance)"` |
| CAPACITY_STALE | `"{name} blocked (CAPACITY_STALE): capacity value is {age_s:.3f} s old (limit 20 s)"` |
| CAPACITY_UNKNOWN | `"{name} blocked (CAPACITY_UNKNOWN): no capacity value"` or `"...: capacity quality {quality!r} is not GOOD"` |
| CAPACITY_INVALID | `"{name} blocked (CAPACITY_INVALID): capacity {kw} kW is not a finite non-negative number"` or `"...: capacity timestamp is {lead_s:.3f} s ahead of as_of (limit 2 s)"` |

Error handling removed and its replacement in the same change (STD-ARCH-5):

| Removed | Replacement |
|---|---|
| `tie_capacity_kw = tie_capacity_kw or {}` + `.get(mrid, 0.0)` (implicit zero) | explicit `entry = None` → CAPACITY_UNKNOWN, machine-readable |
| `transferred > available` skip guard | `tie_capacity_verdict` positive close condition (blocks NaN that the old guard let through) |
| free-text-only skip note | `blocked_ties` entry + note |

## 5. Endpoint — `POST /flisr/plan` in `backend/app/api.py` (U3)

`FlisrRequest` stays in `api.py` (existing convention for HTTP request schemas: `EstimationRequest`, `AgcRequest`). It is an API-layer DTO, not a domain model; it reuses `TieCapacity` and `IsoAwareDatetime` from `models.py`.

```python
class FlisrRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")                    # unknown body field -> 422
    feeder_mrid: StrictStr
    lockout_switch_mrid: StrictStr
    tie_capacity: dict[str, TieCapacity] | None = None
    tie_capacity_kw: dict[str, StrictFloat] | None = None        # deprecated
    as_of: IsoAwareDatetime | None = None

    @field_validator("tie_capacity", "tie_capacity_kw", "as_of", mode="before")
    def _no_null(v): None -> ValueError("omit the field instead of sending null")   # defaults are not validated, so "absent" still works
    @model_validator(mode="after")
    def _mutually_exclusive(self): both not None -> ValueError   # REQ-TIECAP-15 (both {} included)

def server_now() -> datetime:          # FastAPI dependency; tests override via app.dependency_overrides
    return datetime.now(UTC)

def _check_as_of_bound(as_of, now):    # REQ-TIECAP-23; raises RequestValidationError(loc=("body","as_of")) -> 422
    now - as_of > AS_OF_MAX_LAG  or  as_of - now > AS_OF_MAX_LEAD  -> reject   (exactly 60 s / 2 s accepted)

@router.post("/flisr/plan", response_model=RestorationPlan, description=<deprecation + mutual-exclusion note>)
def flisr_plan(request: FlisrRequest, now: datetime = Depends(server_now)) -> RestorationPlan:
    as_of = request.as_of if request.as_of is not None else now     # server clock read once per request
    _check_as_of_bound(as_of, now)                                  # before load_network / build_plan
    ... flisr.build_plan(feeder, lockout, request.tie_capacity_kw,
                         tie_capacity=request.tie_capacity, as_of=as_of)
    KeyError -> 404, FlisrError -> 409   (unchanged); blocked ties -> 200 (REQ-TIECAP-13)
```

Prototype measurements (pydantic 2.14.1 / fastapi 0.143.1, outside the repo): `"kw":"2000"`, `true`, `null` → 422 `float_type`; timestamp `"yesterday"`, `1790000000` → 422; naive → 422 `timezone_aware`; extra field at body and `TieCapacity` level → 422 `extra_forbidden`; `"tie_capacity": null` and `"as_of": null` → 422; both maps `{}` → 422; JSON `NaN` / `-Infinity` → reaches handler (planner then CAPACITY_INVALID); `RequestValidationError` raised in the handler → standard 422 body; the response serialises a UTC `as_of` as `...Z`.

OpenAPI `description` (REQ-TIECAP-17): "`tie_capacity_kw` is deprecated and will be removed one release after this one. It is mutually exclusive with `tie_capacity`; sending both returns 422. Legacy values are treated as quality GOOD with timestamp = as_of." Not `Field(deprecated=True)`: in pydantic 2.14 that emits a `DeprecationWarning` whenever the handler reads the attribute.

## 6. Test strategy

### 6.1 Files and order (from `units.json`; safety skill steps 1–5)

| Unit | File | Content |
|---|---|---|
| U1 | `test_flisr_tie_capacity_characterization.py` | `@pytest.mark.characterization` on `main` via legacy `tie_capacity_kw`; pins isolation, restoration steps + order, customer counts, `transferred_load_kw`; excludes C ∈ (L, L+0.5], missing, non-finite/negative, DEF-FLISR-7 topologies; no-fault plan with `model_dump().get("blocked_ties", []) == []` |
| U1 | `test_flisr_tie_capacity_repro.py` | `xfail(strict=True)`: (a) no entry → expects `blocked_ties` CAPACITY_UNKNOWN; (b) legacy NaN and +inf → expects no close step for `TIE-1201-1405` |
| U2 | `test_flisr_tie_capacity_models.py` | accept/reject classes via `model_validate_json` **and** a FastAPI `TestClient` echo route defined in the test (Python-mode path) |
| U3 | `test_flisr_tie_capacity_planner.py` | `build_plan` with injected `as_of`; boundaries; precedence; per-tie; accounting; notes; legacy parity; ValueError cases |
| U3 | `test_flisr_tie_capacity_api.py` | `TestClient`; `app.dependency_overrides[server_now]` fixed clock; `monkeypatch` of `app.api.flisr.build_plan` with a recorder to assert "not called" on every 422; OpenAPI text |
| U4 | `test_flisr_tie_capacity_invariant.py` | ≥ 500 seeded cases (seed + count printed) |

`backend/tests/test_flisr.py` passes unchanged throughout. All tests that need the shipped model set `CB-1201.open = True` (otherwise 409).

### 6.2 Boundary values (shipped model, `CB-1201` open, L = 1490.0 kW, customers 341)

C = 1490.0 close · 1489.5 close · 1489.4 EXCEEDED · age 19.999 / 20.000 s fresh, 20.001 s STALE · age −1.999 / −2.000 s fresh, −2.001 s INVALID · server clock fixed: as_of −60.000 s / +2.000 s accepted, −60.001 s / +2.001 s 422.

### 6.3 Oracle (depends on Q-DESIGN-1)

Spec §4 / STD-SAFETY-6: an independent oracle in the test files that does not import `app.network` or `app.flisr` helpers: its own BFS for the candidate node set and L, closed-form `L <= C + 0.5`, `age > 20 s`, `age < −2 s`, `quality == "GOOD"`, `isfinite(kw) and kw >= 0`, and the precedence function. Proposed (pending Q-DESIGN-1): oracle literals come from the specification, not from `models.py`, and one test asserts `models.TIE_CAPACITY_*` / `AS_OF_*` equal the specified values, so a wrong constant fails a test instead of moving the oracle with it.

## 7. Requirement → component → test (STD-ARCH-6)

| Requirement | Component | Test strategy |
|---|---|---|
| REQ-TIECAP-1 | `models.TieCapacity`, `IsoAwareDatetime` | U2 models test, both JSON and TestClient paths |
| REQ-TIECAP-2 | `flisr.build_plan` signature, `as_of` resolution | planner test: UTC vs `+02:00` identical plan; naive → `ValueError`; None → UTC now |
| REQ-TIECAP-3 | `flisr.tie_capacity_verdict` (close branch) | planner boundaries §6.2 vs oracle §6.3 |
| REQ-TIECAP-4 | `tie_capacity_verdict` → EXCEEDED; tie loop | planner test 1489.4; oracle |
| REQ-TIECAP-5 | `tie_capacity_verdict` (None / non-GOOD); loop with no default | planner: missing key, None, `{}`, `"BAD"`, `"SUSPECT"`, `"good"`, `""`; inspection of `flisr.py` (no `0.0` default); U1 repro (a) |
| REQ-TIECAP-6 | `tie_capacity_verdict` (`age > MAX_AGE`) | planner ages 19.999 / 20.000 / 20.001 s |
| REQ-TIECAP-7 | `tie_capacity_verdict` (`age < -MAX_LEAD`) | planner ages −1.999 / −2.000 / −2.001 s |
| REQ-TIECAP-8 | `tie_capacity_verdict` (finite, ≥ 0) | planner NaN, ±inf, −1.0, 0.0, −0.0; API raw JSON `NaN`/`Infinity`/`-Infinity`/`-1` → 200 INVALID; U1 repro (b) |
| REQ-TIECAP-9 | `tie_capacity_verdict` statement order; `TieBlockReason` order | planner: every combination vs oracle precedence function |
| REQ-TIECAP-10 | tie loop (per-tie, isolation untouched) | planner two-tie generated topology |
| REQ-TIECAP-11 | `models.BlockedTie`, `TieBlockReason`, `RestorationPlan.blocked_ties` | U2 schema test; planner content and order |
| REQ-TIECAP-12 | `flisr._blocked_note` | planner: note per reason, L/C at 0.1 kW, age |
| REQ-TIECAP-13 | `api.FlisrRequest`, `flisr_plan` | API: 422 list in spec, each asserting planner not called; blocked tie → 200 |
| REQ-TIECAP-14 | `RestorationPlan.as_of`; `build_plan` UTC normalisation; `flisr_plan` as_of resolution | API: `+01:00` echoed as `22:00:00Z`; absent → instant within send/receive window (parsed comparison) |
| REQ-TIECAP-15 | `FlisrRequest._mutually_exclusive`; `build_plan` ValueError | API both present (incl. `{}`) → 422; planner both → ValueError |
| REQ-TIECAP-16 | `flisr._legacy_to_tie_capacity`; `RestorationPlan.deprecations` | planner + API legacy-only parity with GOOD/as_of; `deprecations` asserted both ways |
| REQ-TIECAP-17 | `flisr_plan` route `description` | API: inspect `app.openapi()["paths"]["/flisr/plan"]["post"]["description"]` |
| REQ-TIECAP-18 | tie loop accounting | planner vs oracle sums |
| REQ-TIECAP-19 | `build_plan` no-fault early return | U1 characterization (unchanged after U2/U3) |
| REQ-TIECAP-20 | `build_plan` reads clock once at entry | planner: monkeypatched clock counts one read; inspection |
| REQ-TIECAP-21 | `tie_capacity_verdict` + tie loop | U4 invariant ≥ 500 seeded cases, generator places ties at any node (not tail-only) |
| REQ-TIECAP-22 | unchanged isolation/restoration code paths | U1 characterization pinned on `main` @ 5f6b471 |
| REQ-TIECAP-23 | `api.server_now`, `_check_as_of_bound`, `IsoAwareDatetime` | API with overridden clock: §6.2 bounds, naive, `"yesterday"`, `1790000000` → 422 |

No requirement is unmapped.

## 8. Standards check (verify)

- STD-ARCH-1: constants and types in `models.py`; decision logic in `flisr.py`; request DTO in `api.py` (API layer).
- STD-ARCH-2: one capacity characteristic (`tie_capacity_verdict`) with parameters single-sourced in `models.py`. Test-oracle clause: see Q-DESIGN-1.
- STD-ARCH-3: `models` imports nothing from the app; `flisr` imports `models`/`network`; `api` imports `flisr`/`models`/`network`. No upward import.
- STD-ARCH-4: §3 docstring and §4 table cover absent, stale and out-of-range for every new or changed public function; default is refuse/hold the tie.
- STD-ARCH-5: §4 removed-guard table.
- STD-ARCH-6: §7.
- STD-ARCH-7: this design is handed to the Architect unchanged; Architect does not edit it.
- STD-ARCH-8: no IEC 61850 logical nodes or data objects are added; `blocked_ties` is internal to the planner API.
- STD-SAFETY-2/3/4/5: U1 before production edits, repro xfail, smallest fail-safe change (§4), invariant ≥ 500 (U4).
- STD-SAFETY-6: tolerance 0.5 kW engineering units; per-unit waived by Q-SPEC-4 (record against STD-SAFETY-6 in the PR).
- STD-SAFETY-7: no tool-certification credit claimed; tool classification left to the assessor.
- STD-SAFETY-8: no production systems, secrets or field devices used; prototype ran locally against synthetic bodies.
- STD-GOV-1/2: branch `agent/feature-tie-capacity/design`, trailer on the commit. STD-GOV-7: the platform appends a `Co-Authored-By` trailer carrying a personal name to agent commits; the agent cannot change the commit identity, so this is reported as a compliance note.

## 9. Open question

- **Q-DESIGN-1** — STD-ARCH-2 requires one shared implementation of a threshold characteristic "used by every consumer (firmware, setting tool, test oracle)" and calls duplicates a VIOLATION. STD-SAFETY-6 and specification §4 / REQ-TIECAP-3 require an *independent* closed-form oracle that does not import `app.flisr` helpers, which means restating `L <= C + 0.5`, `age > 20 s`, `age < −2 s` and the precedence in the test. Both cannot hold literally for the test oracle. Which governs here?
  - (a) STD-SAFETY-6: the QA oracle restates the closed form with literals from the specification, plus a test pinning the `models.py` constants to those values; STD-ARCH-2 applies to production consumers only (proposed, §6.3).
  - (b) STD-ARCH-2: tests call `flisr.tie_capacity_verdict`; independence comes only from hand-computed boundary expectations (§6.2), and the spec's oracle clause is amended.
  - (c) Middle: the oracle imports only the constants from `models.py` but restates the comparison and precedence.

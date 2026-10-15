# Design — FLISR restoration respects tie-switch capacity

Run: `feature-tie-capacity` · Stage: DESIGN · Attempt: 3 · Inputs: `specification.md` (attempt 4, complete), `units.json` (U1–U4), `architecture-review.md` (Architect attempt 1, VIOLATION, on `agent/feature-tie-capacity/architect` @ 0584fbb)
Safety classification: **safety-critical** (STD-SAFETY-1). Protected path `backend/app/flisr.py`: two human reviewers (STD-GOV-6).
Status: **BLOCKED on Q-DESIGN-2 and Q-DESIGN-3** (§9). Architect finding A-1 (STD-ARCH-4) is resolved inside the specification's defined input range (§3, §4). Resolving A-1 found two inputs the specification does not decide: a finite negative `Section.load_kw` that makes L understate the load the tie would carry, and how this change composes with the DEF-FLISR-7 hold-open guard on draft PR #13. Each needs a departure from REQ-TIECAP-3 or REQ-TIECAP-21, which the Architect said must be raised as a question, not assumed. Everything else in the design is complete and does not depend on the answers. §9 marks the parts that do.

Changes from attempt 2 (each Architect item, clause and what changed, is in §10):
- **A-1 (STD-ARCH-4, STD-SAFETY-4).** `tie_capacity_verdict` now states preconditions and raises `ValueError` for an out-of-range `transferred_kw` (NaN, ±inf, < 0), a naive or non-datetime `as_of`, a naive `entry.timestamp`, or an `entry` that is not a `TieCapacity`. `build_plan` checks L before calling the verdict and raises `FlisrError` (no plan; HTTP 409, unchanged mapping) for a candidate tie whose L is NaN, ±inf or < 0 (§3, §4, §5). New test rows are in §6.1, §6.2 and §7.
- **O-2 (STD-ARCH-5).** Integration ordering with the DEF-FLISR-7 guard is stated (§4), and the conflict with REQ-TIECAP-21 is raised as Q-DESIGN-3.
- **O-3 (STD-ARCH-2).** The legacy conversion uses `TIE_CAPACITY_GOOD_QUALITY`. P2 now covers `_legacy_to_tie_capacity` and rejects the string literal `"GOOD"` (§4, §6.3).
- **O-4 (STD-SAFETY-6).** O1 now also rejects bare names bound by `from app.models import TIE_CAPACITY_*/AS_OF_*` and attribute access through any alias of `app.models` (§6.3).
- **O-1, O-5.** Accepted as observations, with no design change (§10).
- **STD-SAFETY-7.** A tool-classification argument has been added as a finding for the assessor (§8.1).

Baseline re-measured on `main` @ 5f6b471: `pytest backend -q` → 2 passed; `ruff check backend tools` → 1 pre-existing error in `tools/` (UP017), unrelated to this change.

## 1. Components and layers

Layer map (repo contract): `ui → api → logic → models`. No lower layer imports an upper one (STD-ARCH-3).

| Layer | Module | Change | Imports (allowed) |
|---|---|---|---|
| models | `backend/app/models.py` | New: constants, `IsoAwareDatetime`, `TieCapacity`, `TieBlockReason`, `BlockedTie`. Extended: `RestorationPlan`. | pydantic, stdlib only |
| logic | `backend/app/flisr.py` | New: `tie_capacity_verdict()` (the single capacity characteristic), `_not_finite_nonneg()` (the one finite-and-non-negative predicate, used for C, for L and by the notes), `_legacy_to_tie_capacity()`, `_blocked_note()`. Changed: `build_plan()` signature and tie loop. `locate_fault`, `_isolation_switches`, `_nodes_restored_by` unchanged. | `.models`, `.network` (same layer, as today) |
| logic | `backend/app/network.py` | Unchanged (`load_on_nodes` keeps computing L). | `.models` |
| api | `backend/app/api.py` | Changed: `FlisrRequest`, `flisr_plan` route; new `server_now()` dependency, `_check_as_of_bound()`. | `.flisr`, `.models`, `.network` |
| ui | `console/**` | Unchanged (does not call `/flisr/plan`). | — |

Data flow (HTTP): JSON body → FastAPI/Pydantic request validation (`FlisrRequest`, `TieCapacity`) → `_check_as_of_bound(as_of, server_now)` → `flisr.build_plan(..., tie_capacity | tie_capacity_kw, as_of=resolved)` → per candidate tie `tie_capacity_verdict(entry, L, as_of)` → `RestorationPlan` (with `blocked_ties`, `as_of`, `deprecations`) → HTTP 200. Any validation failure → HTTP 422 and `build_plan` is never called.

## 2. Data models — `backend/app/models.py` (U2, extended in U3)

U2 adds the characteristic constants, `IsoAwareDatetime`, `TieCapacity`, `TieBlockReason`, `BlockedTie` and `RestorationPlan.blocked_ties`, all additive. U3 adds only `RestorationPlan.as_of` and `RestorationPlan.deprecations` (units.json U3 scope note).

Models and constants only; no plant decision logic (STD-ARCH-1). The one validator function is a type parser (it decides whether an input *is* an ISO-8601 string), not a plant decision.

```python
# Tie-capacity characteristic parameters: the ONE production source (STD-ARCH-1/2, Q-DESIGN-1).
# Imported by flisr.tie_capacity_verdict, flisr._blocked_note, api._check_as_of_bound and the
# /flisr/plan OpenAPI description. No production module restates these values (spec Q-SPEC-1/2/4/10/12).
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

There is one implementation of the capacity decision. Its parameters come only from the `models.py` constants in §2. Production consumers (Q-DESIGN-1):

| Consumer | Uses |
|---|---|
| `flisr.build_plan` tie loop (planner) | calls `tie_capacity_verdict`; no comparison of its own |
| `flisr._blocked_note` (operator notes) | formats `TIE_CAPACITY_TOLERANCE_KW`, `TIE_CAPACITY_MAX_AGE`, `TIE_CAPACITY_MAX_LEAD`; never re-derives the reason, only formats the reason the verdict returned |
| `api._check_as_of_bound` (endpoint) | `AS_OF_MAX_LAG`, `AS_OF_MAX_LEAD` |
| `api` route `description` (OpenAPI) | formats the same constants into the deprecation note |

No production module other than `models.py` contains the literals 0.5, 20, 2 or 60 for these purposes. A test enforces this (§6.3, check P2).

```python
def _not_finite_nonneg(x) -> bool:
    """True when x is not a real number (bool excluded), or is NaN, ±inf or < 0. -0.0 and 0.0 pass."""
    return not (isinstance(x, (int, float)) and not isinstance(x, bool)
                and math.isfinite(x) and x >= 0.0)

def tie_capacity_verdict(
    entry: TieCapacity | None, transferred_kw: float, as_of: datetime
) -> TieBlockReason | None:
    """None = the tie may close. Otherwise the first applicable reason (REQ-TIECAP-9).

    Preconditions (STD-ARCH-4). Each one is checked before any comparison. A violation raises
    ValueError and returns no verdict, so the caller cannot treat it as "may close":
      - transferred_kw is finite and >= 0 (spec §0: L range L >= 0). NaN, +inf, -inf and
        negative values raise; build_plan converts this into FlisrError (no plan), see §4.
      - as_of is a timezone-aware datetime. Naive or non-datetime raises.
      - entry is None or a TieCapacity whose timestamp is timezone-aware. Any other type, or a
        naive timestamp (reachable only through model_construct, which skips validation),
        raises.
    Decisions on valid inputs:
      absent entry -> CAPACITY_UNKNOWN; kw not finite or < 0, or timestamp more than 2 s ahead of
      as_of -> CAPACITY_INVALID; quality != GOOD -> CAPACITY_UNKNOWN; older than 20 s ->
      CAPACITY_STALE; L <= C + 0.5 kW -> None (close); otherwise CAPACITY_EXCEEDED.
    Never substitutes, clamps or defaults a value."""
    if _not_finite_nonneg(transferred_kw):                       -> raise ValueError
    if not _is_aware_datetime(as_of):                            -> raise ValueError
    if entry is None:                                            -> CAPACITY_UNKNOWN
    if not isinstance(entry, TieCapacity) or not _is_aware_datetime(entry.timestamp):
                                                                 -> raise ValueError
    age = as_of - entry.timestamp                                # timedelta, exact µs
    if _not_finite_nonneg(entry.kw) or age < -TIE_CAPACITY_MAX_LEAD:
                                                                 -> CAPACITY_INVALID
    if entry.quality != TIE_CAPACITY_GOOD_QUALITY:               -> CAPACITY_UNKNOWN
    if age > TIE_CAPACITY_MAX_AGE:                               -> CAPACITY_STALE
    if transferred_kw <= entry.kw + TIE_CAPACITY_TOLERANCE_KW:   -> None (close)
    return CAPACITY_EXCEEDED
```

`_is_aware_datetime(x)` is `isinstance(x, datetime) and x.utcoffset() is not None`. It is a type check, not a threshold.

Design decisions:
- **Out-of-range L is refused. It is never blocked or closed (A-1).** The specification defines L ≥ 0 (§0 Definitions), so L outside that range means the network model is wrong, not that the capacity is. No `BlockedTie` reason fits: the four reasons describe C, not L. Adding a fifth reason would change REQ-TIECAP-11 and Q-SPEC-5. The repo safety skill (step 4: "refuse (raise the module's error type …)") and STD-ARCH-4 ("refuse or hold") make refusal the default, so the verdict raises. Measured on `main` @ 5f6b471 with the shipped model (`CB-1201` open, C = 0.0): `SEC-1201-04.load_kw` = NaN, −inf or −120.0 each **closes** `TIE-1201-1405` today. The attempt-2 design still closed on −inf and −120.0. Attempt 3 closes on none of them.
- **Why the precondition comes before the absent-entry check.** If the entry check came first, a NaN L with no capacity entry would return CAPACITY_UNKNOWN and hide a corrupt network model. Network-model faults therefore take priority over capacity reasons. REQ-TIECAP-9 orders capacity reasons only and is unaffected.
- **Positive close condition is kept.** It is now defence in depth: with the L precondition in place no NaN can reach `L <= C + τ`, but if it did, the comparison would be False and the tie would block.
- **Ages compared as `timedelta`**, never as float seconds, so the 20.000 s / 20.001 s and −2.000 s / −2.001 s boundaries are exact at microsecond resolution (measured: `20.001 s > 20 s` True, `20 s > 20 s` False). A naive operand is rejected by the precondition rather than left to raise `TypeError` from the subtraction (measured: `can't subtract offset-naive and offset-aware datetimes`).
- `kw = -0.0` and `L = -0.0` pass `>= 0.0` (valid, as the spec requires for kw; L = −0.0 is the sum of zero-load sections).
- A `kw` that is not a real number (reachable only through `model_construct`) is CAPACITY_INVALID ("not a finite number", Q-SPEC-9), not a crash.
- Precedence is the order of the `if` statements; a missing entry can only be UNKNOWN.
- **Not decided here (Q-DESIGN-2).** A finite negative `Section.load_kw` inside a candidate set whose sum L is still ≥ 0 meets the precondition. It is evaluated as REQ-TIECAP-3 states, which can understate the load the tie would carry (§9).

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
| `tie_capacity_kw` given (legacy) | each entry → `TieCapacity.model_construct(kw=v, timestamp=as_of, quality=TIE_CAPACITY_GOOD_QUALITY)` (O-3) (no re-validation, so NaN/±inf/negative survive and become CAPACITY_INVALID); `plan.deprecations = ["tie_capacity_kw"]` (REQ-TIECAP-16) |
| both None, or `{}` | every candidate tie CAPACITY_UNKNOWN (REQ-TIECAP-5) |
| entry for a non-candidate tie | ignored, as today (spec §3) |
| candidate tie with L NaN, +inf, −inf or < 0 (from `Section.load_kw`) | `FlisrError("{name}: transferred load {L} kW is not a finite non-negative number; network model invalid, no plan")`. No plan; HTTP 409 (A-1). `CB-1201` stays in lockout, so the faulted section stays de-energised and customers wait for manual switching. This is the fail-safe state. |
| candidate tie with a finite negative section load but L ≥ 0 | evaluated per REQ-TIECAP-3 (not decided, Q-DESIGN-2) |
| a `tie_capacity` / `tie_capacity_kw` value of the wrong Python type (direct callers only; HTTP rejects it with 422) | `TieCapacity` slot holding a non-`TieCapacity` value → `ValueError`, no plan. Legacy value not a real number → CAPACITY_INVALID |
| lockout not open / no isolating switch | `FlisrError`, unchanged |
| no fault indication | unchanged early return; `blocked_ties` stays `[]` (REQ-TIECAP-19) |

Why `ValueError` and not `FlisrError`: `FlisrError` means "the network state does not allow a defensible plan" and maps to HTTP 409. Naive `as_of` and both-maps are caller contract violations that HTTP validation already rejects with 422, so they never reach `build_plan` from `api.py`; a direct Python caller gets an exception and no plan either way.

Tie loop (replaces `flisr.py:92-121`; isolation, lockout re-close and `_nodes_restored_by` untouched, REQ-TIECAP-10):

```text
for switch in feeder.switches:                 # order => blocked_ties order (REQ-TIECAP-11)
    skip silently if not tie / not SCADA / empty candidate set     # as today
    # [DEF-FLISR-7 hold-open guard, if PR #13 lands first, goes HERE, before L is computed. See Q-DESIGN-3.]
    L = load_on_nodes(feeder, candidate_nodes)
    if _not_finite_nonneg(L): raise FlisrError(...)               # A-1: no plan from an out-of-range model
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
| CAPACITY_EXCEEDED | `"{name} blocked (CAPACITY_EXCEEDED): {L:.1f} kW to transfer exceeds {C:.1f} kW available capacity (+{TIE_CAPACITY_TOLERANCE_KW:g} kW tolerance)"` |
| CAPACITY_STALE | `"{name} blocked (CAPACITY_STALE): capacity value is {age_s:.3f} s old (limit {TIE_CAPACITY_MAX_AGE.total_seconds():g} s)"` |
| CAPACITY_UNKNOWN | `"{name} blocked (CAPACITY_UNKNOWN): no capacity value"` or `"...: capacity quality {quality!r} is not GOOD"` |
| CAPACITY_INVALID | `"{name} blocked (CAPACITY_INVALID): capacity {kw} kW is not a finite non-negative number"` or `"...: capacity timestamp is {lead_s:.3f} s ahead of as_of (limit {TIE_CAPACITY_MAX_LEAD.total_seconds():g} s)"` |

Rendered on the shipped model these read, for example, `+0.5 kW tolerance`, `limit 20 s`, `limit 2 s`. The limit text comes from the same constants the verdict uses, so a note can never state a limit different from the one applied. `_blocked_note` receives the reason from `tie_capacity_verdict` and does not compare anything itself. For UNKNOWN and INVALID it chooses between the two message variants with presence and type checks only (entry is None or not; which INVALID sub-condition holds). Those sub-condition checks reuse the verdict's predicate `_not_finite_nonneg` in `flisr.py`; they are not re-implemented.

Error handling removed and its replacement in the same change (STD-ARCH-5):

| Removed | Replacement |
|---|---|
| `tie_capacity_kw = tie_capacity_kw or {}` + `.get(mrid, 0.0)` (implicit zero) | explicit `entry = None` → CAPACITY_UNKNOWN, machine-readable |
| `transferred > available` skip guard | `tie_capacity_verdict` positive close condition (blocks NaN that the old guard let through) |
| free-text-only skip note | `blocked_ties` entry + note |
| (none today: a NaN / ±inf / negative L is compared numerically and closes the tie) | new `FlisrError` precondition on L (A-1); verdict `ValueError` preconditions |

Integration with DEF-FLISR-7 (O-2, STD-ARCH-5). Draft PR #13 (`agent/rca-backfeed/fix`) adds a hold-open guard at `flisr.py:97`, in the same loop. The guard runs after the empty-candidate skip and before L is computed. If PR #13 lands first, Coding/Integrate must keep that guard in exactly that position, ahead of the L precondition and `tie_capacity_verdict`. Dropping it, or moving it after the capacity check, violates STD-ARCH-5 and the spec's "neither fix nor mask DEF-FLISR-7". Whether a held-open tie appears in `blocked_ties` is not decided: REQ-TIECAP-21 currently requires every candidate tie that is not closed to be listed (Q-DESIGN-3).

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
    KeyError -> 404, FlisrError -> 409   (unchanged; now also out-of-range L, A-1); blocked ties -> 200 (REQ-TIECAP-13)
```

Prototype measurements (pydantic 2.14.1 / fastapi 0.143.1, outside the repo): `"kw":"2000"`, `true`, `null` → 422 `float_type`; timestamp `"yesterday"`, `1790000000` → 422; naive → 422 `timezone_aware`; extra field at body and `TieCapacity` level → 422 `extra_forbidden`; `"tie_capacity": null` and `"as_of": null` → 422; both maps `{}` → 422; JSON `NaN` / `-Infinity` → reaches handler (planner then CAPACITY_INVALID); `RequestValidationError` raised in the handler → standard 422 body; the response serialises a UTC `as_of` as `...Z`.

OpenAPI `description` (REQ-TIECAP-17), a module-level string in `api.py` built from the `models.py` constants (for example the 0.5 kW tolerance and the 20 s / 2 s limits) so it cannot drift from them: "`tie_capacity_kw` is deprecated and will be removed one release after this one. It is mutually exclusive with `tie_capacity`; sending both returns 422. Legacy values are treated as quality GOOD with timestamp = as_of." Not `Field(deprecated=True)`: in pydantic 2.14 that emits a `DeprecationWarning` whenever the handler reads the attribute.

## 6. Test strategy

### 6.1 Files and order (from `units.json`; safety skill steps 1–5)

| Unit | File | Content |
|---|---|---|
| U1 | `test_flisr_tie_capacity_characterization.py` | `@pytest.mark.characterization` on `main` via legacy `tie_capacity_kw`; pins isolation, restoration steps + order, customer counts, `transferred_load_kw`; excludes C ∈ (L, L+0.5], missing, non-finite/negative, DEF-FLISR-7 topologies; no-fault plan with `model_dump().get("blocked_ties", []) == []` |
| U1 | `test_flisr_tie_capacity_repro.py` | `xfail(strict=True)`: (a) no entry → expects `blocked_ties` CAPACITY_UNKNOWN; (b) legacy NaN and +inf → expects no close step for `TIE-1201-1405` |
| U2 | `test_flisr_tie_capacity_models.py` | accept/reject classes via `model_validate_json` **and** a FastAPI `TestClient` echo route defined in the test (Python-mode path) |
| U3 | `test_flisr_tie_capacity_planner.py` | `build_plan` with injected `as_of`; boundaries; precedence; per-tie; accounting; notes; legacy parity; ValueError cases; A-1 preconditions: `tie_capacity_verdict` called directly with L ∈ {NaN, +inf, −inf, −120.0, −1e-9} → `ValueError`, L ∈ {0.0, −0.0} accepted; naive `as_of`, non-datetime `as_of`, naive `entry.timestamp` via `model_construct`, entry of the wrong type → `ValueError`; non-real `kw` via `model_construct` → CAPACITY_INVALID; `build_plan` on a deep copy of the shipped model with `SEC-1201-04.load_kw` ∈ {NaN, +inf, −inf, −120.0} and each capacity state (missing, GOOD 0.0, GOOD 2000.0) → `FlisrError`, no plan |
| U3 | `test_flisr_tie_capacity_api.py` | `TestClient`; `app.dependency_overrides[server_now]` fixed clock; `monkeypatch` of `app.api.load_network` with a model whose candidate L is NaN → 409, body carries no plan; `monkeypatch` of `app.api.flisr.build_plan` with a recorder to assert "not called" on every 422; OpenAPI text |
| U4 | `test_flisr_tie_capacity_invariant.py` | ≥ 500 seeded cases (seed + count printed). At least 5 % of the cases inject an out-of-range L (NaN, ±inf, negative total). For those the invariant is "`FlisrError`, no plan", checked against an oracle predicate on the oracle's own L |

`backend/tests/test_flisr.py` passes unchanged throughout. All tests that need the shipped model set `CB-1201.open = True` (otherwise 409).

### 6.2 Boundary values (shipped model, `CB-1201` open, L = 1490.0 kW, customers 341)

C = 1490.0 close · 1489.5 close · 1489.4 EXCEEDED · age 19.999 / 20.000 s fresh, 20.001 s STALE · age −1.999 / −2.000 s fresh, −2.001 s INVALID · server clock fixed: as_of −60.000 s / +2.000 s accepted, −60.001 s / +2.001 s 422 · `SEC-1201-04.load_kw` NaN / +inf / −inf / −120.0 → `FlisrError` (today: NaN, −inf and −120.0 close the tie; +inf blocks, measured), 0.0 → valid L.

### 6.3 Oracle and the scoped STD-ARCH-2 waiver (Q-DESIGN-1)

**Waiver (explicit and scoped).** STD-ARCH-2 says one shared implementation of a numerically sensitive characteristic is used by every consumer, test oracle included, and calls duplicates a VIOLATION. STD-SAFETY-6 requires operate boundaries to be checked against an *independent* closed-form oracle. Per Q-DESIGN-1 (principal-engineer-standin), **STD-SAFETY-6 governs the test oracle** and **STD-ARCH-2 applies to production consumers only** (planner, endpoint, notes; §3). Scope of the waiver:

- Covers only the QA oracle functions in `backend/tests/test_flisr_tie_capacity_planner.py`, `test_flisr_tie_capacity_api.py` and `test_flisr_tie_capacity_invariant.py`, which restate the closed forms below.
- Does not cover any module under `backend/app/`. A second production implementation of the characteristic, or a restated production literal, is still a STD-ARCH-2 VIOLATION.
- The U3 and U4 oracles are separate restatements: units.json says U4's oracle is "implemented in the test file". Both use the literals from the specification. Under the waiver this is intended: more diversity, no shared defect.

**Oracle content.** The oracle lives under `backend/tests`. It does not import `app.flisr` or `app.network` and does not use the `models.py` threshold constants (Q-DESIGN-1: "must not import app.flisr or share its threshold code"). It may read `app.models` data types (`Feeder`, `Section`, `Switch`, `TieCapacity`) as plain data. Functions are named `oracle_*`:

| Oracle function | Closed form (literals from the specification) |
|---|---|
| `oracle_candidate_nodes(feeder, tie_mrid, opened)` | its own BFS over the test topology: nodes reachable from the tie's `from_node` with isolation switches open and the tie closed, minus nodes reachable from `source_node` (spec "Candidate tie" definition) |
| `oracle_load_kw(feeder, nodes)` / `oracle_customers(...)` | Σ `load_kw` / `customers` of sections whose `to_node` ∈ nodes |
| `oracle_l_in_range(L)` | `isfinite(L) and L >= 0` (spec §0 range); False ⇒ expect `FlisrError` |
| `oracle_reason(entry, L, as_of)` | `None` → UNKNOWN; `not (isfinite(kw) and kw >= 0) or age < timedelta(seconds=-2)` → INVALID; `quality != "GOOD"` → UNKNOWN; `age > timedelta(seconds=20)` → STALE; `L <= kw + 0.5` → close; else EXCEEDED (REQ-TIECAP-9 precedence) |
| `oracle_as_of_ok(as_of, now)` (API test) | `now - as_of <= timedelta(seconds=60) and as_of - now <= timedelta(seconds=2)` |

Tolerance: 0.5 kW in engineering units. Per-unit statement waived by Q-SPEC-4; the PR records this waiver against STD-SAFETY-6.

**Checks that keep the oracle independent and the production source single** (all in the U2/U3/U4 files already listed in units.json; no new files):

- **O1 — oracle independence** (planner, API and invariant test files): an `ast` check of the test module asserts that no `oracle_*` function refers to a name bound by `from app.flisr …`, `from app.network …`, `import app.flisr` / `app.network`, or to a `TIE_CAPACITY_*` / `AS_OF_*` constant, reached either through attribute access on any alias of `app.models` (`models.X`, `m.X` after `import app.models as m`, `from app import models as mm`) or as a bare name bound by `from app.models import TIE_CAPACITY_* / AS_OF_*` (O-4). The check walks every `Import` / `ImportFrom` in the module to collect the aliases and bound names, then walks each `oracle_*` body for `Name` and `Attribute` nodes. The module may import `build_plan` / the app as the subject under test; only the oracle functions are constrained.
- **P1 — constant pin** (U2, `test_flisr_tie_capacity_models.py`): asserts `TIE_CAPACITY_TOLERANCE_KW == 0.5`, `TIE_CAPACITY_MAX_AGE == timedelta(seconds=20)`, `TIE_CAPACITY_MAX_LEAD == timedelta(seconds=2)`, `AS_OF_MAX_LAG == timedelta(seconds=60)`, `AS_OF_MAX_LEAD == timedelta(seconds=2)`, `TIE_CAPACITY_GOOD_QUALITY == "GOOD"`, using spec literals. A wrong constant then fails a test; the oracle does not move with it.
- **P2 — no restated production literal** (U3, planner test): an `ast` check of `tie_capacity_verdict`, `_not_finite_nonneg`, `_blocked_note`, `_legacy_to_tie_capacity` (from `app/flisr.py` source) and `_check_as_of_bound` plus the route description builder (from `app/api.py` source) asserts no numeric constant other than `0` / `0.0`, no `timedelta(...)` call, and no string constant `"GOOD"` (O-3). This mechanically enforces §3's single production source.
- **Oracle self-check** (planner test): the oracle reproduces the §6.2 hand-computed shipped-model values (L = 1490.0 kW, 341 customers, the boundary verdicts) before it is used against `build_plan`.

## 7. Requirement → component → test (STD-ARCH-6)

| Requirement | Component | Test strategy |
|---|---|---|
| REQ-TIECAP-1 | `models.TieCapacity`, `IsoAwareDatetime` | U2 models test, both JSON and TestClient paths |
| REQ-TIECAP-2 | `flisr.build_plan` signature, `as_of` resolution; `tie_capacity_verdict` as_of precondition | planner test: UTC vs `+02:00` identical plan; naive → `ValueError`; None → UTC now; verdict direct with naive / non-datetime `as_of` → `ValueError` (A-1) |
| REQ-TIECAP-3 | `flisr.tie_capacity_verdict` (close branch, L precondition); `build_plan` L check → `FlisrError`; constants `models.TIE_CAPACITY_TOLERANCE_KW` | planner boundaries §6.2 vs independent `oracle_reason` / `oracle_candidate_nodes` / `oracle_load_kw` (§6.3); out-of-range L rows (§6.1) vs `oracle_l_in_range`; O1, P1, P2 |
| REQ-TIECAP-4 | `tie_capacity_verdict` → EXCEEDED; tie loop | planner test 1489.4; oracle |
| REQ-TIECAP-5 | `tie_capacity_verdict` (None / non-GOOD); loop with no default | planner: missing key, None, `{}`, `"BAD"`, `"SUSPECT"`, `"good"`, `""`; inspection of `flisr.py` (no `0.0` default); U1 repro (a) |
| REQ-TIECAP-6 | `tie_capacity_verdict` (`age > TIE_CAPACITY_MAX_AGE`) | planner ages 19.999 / 20.000 / 20.001 s vs `oracle_reason`; P1 |
| REQ-TIECAP-7 | `tie_capacity_verdict` (`age < -TIE_CAPACITY_MAX_LEAD`) | planner ages −1.999 / −2.000 / −2.001 s vs `oracle_reason`; P1 |
| REQ-TIECAP-8 | `tie_capacity_verdict` (finite, ≥ 0) | planner NaN, ±inf, −1.0, 0.0, −0.0; API raw JSON `NaN`/`Infinity`/`-Infinity`/`-1` → 200 INVALID; U1 repro (b) |
| REQ-TIECAP-9 | `tie_capacity_verdict` statement order; `TieBlockReason` order | planner: every combination of {invalid kw, future > 2 s, non-GOOD, stale, exceeded} vs `oracle_reason` |
| REQ-TIECAP-10 | tie loop (per-tie, isolation untouched) | planner two-tie generated topology |
| REQ-TIECAP-11 | `models.BlockedTie`, `TieBlockReason`, `RestorationPlan.blocked_ties` | U2 schema test; planner content and order |
| REQ-TIECAP-12 | `flisr._blocked_note` (limits formatted from `models.py` constants) | planner: note per reason, L/C at 0.1 kW, age; P2 (no literal limits in the note code) |
| REQ-TIECAP-13 | `api.FlisrRequest`, `flisr_plan` | API: 422 list in spec, each asserting planner not called; blocked tie → 200 |
| REQ-TIECAP-14 | `RestorationPlan.as_of`; `build_plan` UTC normalisation; `flisr_plan` as_of resolution | API: `+01:00` echoed as `22:00:00Z`; absent → instant within send/receive window (parsed comparison) |
| REQ-TIECAP-15 | `FlisrRequest._mutually_exclusive`; `build_plan` ValueError | API both present (incl. `{}`) → 422; planner both → ValueError |
| REQ-TIECAP-16 | `flisr._legacy_to_tie_capacity`; `RestorationPlan.deprecations` | planner + API legacy-only parity with GOOD/as_of; `deprecations` asserted both ways |
| REQ-TIECAP-17 | `flisr_plan` route `description` | API: inspect `app.openapi()["paths"]["/flisr/plan"]["post"]["description"]` |
| REQ-TIECAP-18 | tie loop accounting | planner vs oracle sums |
| REQ-TIECAP-19 | `build_plan` no-fault early return | U1 characterization (unchanged after U2/U3) |
| REQ-TIECAP-20 | `build_plan` reads clock once at entry | planner: monkeypatched clock counts one read; inspection |
| REQ-TIECAP-21 | `tie_capacity_verdict` + tie loop + L precondition | U4 invariant ≥ 500 seeded cases, including out-of-range-L cases that must produce no plan, generator places ties at any node (not tail-only); oracle restated in the invariant file (§6.3 waiver), O1 |
| REQ-TIECAP-22 | unchanged isolation/restoration code paths | U1 characterization pinned on `main` @ 5f6b471 |
| REQ-TIECAP-23 | `api.server_now`, `_check_as_of_bound` (`models.AS_OF_MAX_LAG` / `AS_OF_MAX_LEAD`), `IsoAwareDatetime` | API with overridden clock: §6.2 bounds vs `oracle_as_of_ok`, naive, `"yesterday"`, `1790000000` → 422, planner not called; O1, P1, P2 |

No requirement is unmapped.

## 8. Standards check (verify)

- STD-ARCH-1: constants and types in `models.py`; decision logic in `flisr.py`; request DTO in `api.py` (API layer).
- STD-ARCH-2: one production capacity characteristic (`tie_capacity_verdict`); parameters single-sourced in `models.py` and imported by every production consumer (planner, notes, endpoint, OpenAPI text; §3), enforced by P2. Test oracle: scoped waiver per Q-DESIGN-1 (§6.3).
- STD-ARCH-3: `models` imports nothing from the app; `flisr` imports `models`/`network`; `api` imports `flisr`/`models`/`network`. No upward import.
- STD-ARCH-4: the §3 docstring states the preconditions and decisions of `tie_capacity_verdict` for every input: `entry` absent, wrong type, naive timestamp, non-finite, negative or non-real `kw`, stale, future-dated, non-GOOD; `transferred_kw` NaN, ±inf or negative; `as_of` naive or non-datetime. The §4 table does the same for `build_plan`: both maps, naive or absent `as_of`, legacy, wrong-type values, out-of-range L, non-candidate entries, lockout, no fault. §5 does the same for the endpoint. Fail-safe in every row: refuse the plan (raise), or block the tie. Nothing is closed on a guessed or out-of-range value. Not decided: a negative section load inside a non-negative L (Q-DESIGN-2), stated and open.
- STD-ARCH-5: §4 removed-guard table. The DEF-FLISR-7 guard on PR #13 is kept, in a stated position, if that PR lands first (§4, Q-DESIGN-3).
- STD-ARCH-6: §7.
- STD-ARCH-7: this design is handed to the Architect unchanged; Architect does not edit it.
- STD-ARCH-8: no IEC 61850 logical nodes or data objects are added; `blocked_ties` is internal to the planner API.
- STD-SAFETY-2/3/4/5: U1 before production edits, repro xfail, smallest fail-safe change (§4), invariant ≥ 500 (U4).
- STD-SAFETY-6: independent closed-form oracle under `backend/tests`, not importing `app.flisr` / `app.network` or the threshold constants (O1); boundaries §6.2; tolerance 0.5 kW engineering units; per-unit waived by Q-SPEC-4 (record against STD-SAFETY-6 in the PR).
- STD-SAFETY-7: no tool-certification credit claimed; tool-classification argument as a finding in §8.1.
- STD-SAFETY-8: no production systems, secrets or field devices used; prototype ran locally against synthetic bodies.
- STD-GOV-1/2: branch `agent/feature-tie-capacity/design`, trailer on the commit. STD-GOV-7: the platform appends a `Co-Authored-By` trailer carrying a personal name to agent commits; the agent cannot change the commit identity, so this is reported as a compliance note.

### 8.1 Tool-classification argument (STD-SAFETY-7, finding for the assessor; no credit claimed)

- **The design agent (this stage) and the Coding agent.** Their output becomes executable code, so they can introduce faults directly. The argument treats them as **T3**-like. Mitigation: no output is trusted on the agent's word. Two human reviewers check the protected path (STD-GOV-6), the Architect review is independent (STD-ARCH-7), the QA oracle is independent (§6.3), and the invariant runs over ≥ 500 seeded cases (STD-SAFETY-5).
- **pytest, ruff, and the `ast` checks O1/P1/P2.** These are verification tools. They can fail to detect a fault but cannot insert one, so they are **T2**. Their failure mode (a missed defect) is covered by the diversity of oracle versus implementation and by human review.
- **pydantic 2.14.1 and FastAPI 0.143.1.** These are runtime libraries that ship in the executable, not tools. They fall under the IEC 61508-3 pre-existing software arguments (7.4.4 / 7.4.2.12). The validation behaviour the design relies on is measured, not assumed: §2 and §5 list the measurements, and U2/U3 tests pin them so that a library upgrade that changes it fails CI.
- **The assessor decides.** This is an argument for the assessor, not a classification decision.

## 9. Open questions

Two questions are open. Both come from resolving A-1 and the Architect's O-2. The Architect told the Design stage to raise them, not assume an answer, because the fail-safe answer to each departs from REQ-TIECAP-3 or REQ-TIECAP-21 as written.

### Q-DESIGN-2 — negative `Section.load_kw` inside a non-negative L (REQ-TIECAP-3, spec §0 definition of L)

**The gap.** The specification defines L as the sum of `Section.load_kw` over the candidate sections, with range L ≥ 0. It does not say whether one section may have a negative `load_kw`. `Section.load_kw` is an unconstrained float (`models.py:40`). A negative value would usually mean net export from distributed generation. During a fault, that generation normally trips on loss of supply (anti-islanding), so the alternate feeder picks up the gross load, not the net. Measured on `main` @ 5f6b471: on the shipped model with `CB-1201` open, I added a 10-customer spur section after `SEC-1201-04` with `load_kw = -600.0`. With C = 1000.0 the plan **closes `TIE-1201-1405`** with `transferred_load_kw = 890.0`. The non-negative section loads alone total 1490 kW, which is 490 kW over C. The design as written follows REQ-TIECAP-3 literally (L = 890 ≤ 1000.5 → close), and so would this design.

**Options.**
- (a) **Refuse the plan.** If any section in a candidate set has `load_kw < 0`, `build_plan` raises `FlisrError`, as it does for an out-of-range L (§4). This needs REQ-TIECAP-3 and REQ-TIECAP-21 to be scoped to "all candidate-section loads ≥ 0". Recommended: it is fail-safe and the smallest rule (STD-ARCH-4, STD-SAFETY-4). A model with negative loads gets no automatic restoration until someone decides what a negative load means.
- (b) **Evaluate the gross load.** L = Σ max(load_kw, 0). This changes the spec's definition of L and needs domain sign-off that DG output is never counted.
- (c) **Keep REQ-TIECAP-3 as written.** Net L is used and the residual risk is accepted. Reviewers sign off on the understatement.
- (d) **Declare it out of scope.** The network model must not contain negative loads, the integration/model team enforces this, and the design records it as a scope exclusion with no runtime check.

**Depends on the answer.** §4 table row "finite negative section load", the §3 last design decision, P-tests for REQ-TIECAP-3 / REQ-TIECAP-21, and the U4 generator's load range. With option (a) or (b), Q-SPEC owners must amend REQ-TIECAP-3/21. With (c) or (d), the specification records the exclusion.

### Q-DESIGN-3 — composition with the DEF-FLISR-7 hold-open guard (draft PR #13) (REQ-TIECAP-11, REQ-TIECAP-21)

**The gap.** Draft PR #13 (`agent/rca-backfeed/fix`) holds a SCADA tie open, with a free-text note and no `blocked_ties` entry, when its pick-up set contains a faulted-section endpoint. That tie is a "candidate tie" under the spec's definition (non-empty `_nodes_restored_by` set) and is not closed. REQ-TIECAP-21 requires "every candidate tie not closed shall appear exactly once in `blocked_ties` with the reason the REQ-TIECAP-9 precedence gives", and no capacity reason fits a held-open tie. Whichever of the two changes lands second will therefore break REQ-TIECAP-21 or the spec's "neither fix nor mask DEF-FLISR-7" rule. Today, on `main` @ 5f6b471, there is no conflict.

**Options.**
- (a) **Exclude held-open ties.** A tie held open by the DEF-FLISR-7 guard is not a candidate tie for REQ-TIECAP-11/18/21. It stays out of `blocked_ties`, keeps its DEF-FLISR-7 note, and the guard runs before L and the verdict (§4 loop position). The U4 oracle excludes ties whose oracle pick-up set holds a faulted endpoint, but only once PR #13 has landed. Recommended: no new reason code, and each defect run owns its own rule.
- (b) **Add a reason code.** A fifth `BlockedTie` reason, e.g. `BACKFEED_FAULTED_SECTION`, ordered before CAPACITY_INVALID. This changes Q-SPEC-5's closed enum and REQ-TIECAP-9/11, and makes this change partly fix DEF-FLISR-7's reporting.
- (c) **Fix the order.** A merge order is chosen, and the second change amends its own requirements (its owner decides).

**Depends on the answer.** The §4 loop comment and integration note, the U4 oracle and generator, and the REQ-TIECAP-21 test. Nothing else in U1–U3.

### Resolved earlier

- **Q-DESIGN-1** (principal-engineer-standin) → §3, §6.3, §7, §8. STD-SAFETY-6 governs the test oracle, which is independent, lives under `backend/tests` and imports neither `app.flisr` nor the threshold code. STD-ARCH-2 governs production consumers only: tolerance, max age and max lead (plus the as_of bounds) live in `models.py`, and the planner, notes and endpoint import them. The waiver is scoped and recorded in §6.3.

## 10. Architect feedback (iteration 1, VIOLATION) — resolution by item

| Item | Clause | Resolution in attempt 3 |
|---|---|---|
| A-1 | STD-ARCH-4, STD-SAFETY-4 | **Resolved within the specified range.** §3: `tie_capacity_verdict` states and enforces preconditions (`ValueError`) for L NaN / ±inf / < 0, naive or non-datetime `as_of`, naive `entry.timestamp`, wrong-type entry. §4: `build_plan` raises `FlisrError` (no plan, 409) for out-of-range L, checked before the verdict and before capacity reasons. Tests: §6.1 planner/API rows, §6.2 boundary rows, U4 out-of-range cases, §7 REQ-TIECAP-2/3/21. The §8 STD-ARCH-4 claim is rewritten to list every input. No new `BlockedTie` reason, and no change to REQ-TIECAP-3/9/21 within L ≥ 0. Residual negative-section-load case raised as Q-DESIGN-2, as the review instructed. |
| O-1 | STD-ARCH-1 | Accepted; `_require_iso_string` stays in `models.py` as a type parser. No change. |
| O-2 | STD-ARCH-5 | Guard position stated (§4 loop and integration note); `blocked_ties` conflict raised as Q-DESIGN-3. |
| O-3 | STD-ARCH-2 | Legacy conversion uses `TIE_CAPACITY_GOOD_QUALITY` (§4); P2 covers `_legacy_to_tie_capacity` and rejects `"GOOD"` literals (§6.3). |
| O-4 | STD-SAFETY-6 | O1 extended to bare `from app.models import …` names and any module alias (§6.3). |
| O-5 | STD-GOV-7 | Compliance note carried forward: the platform appends a `Co-Authored-By` trailer with a personal name to agent commits. The agent cannot change the commit identity. |
| (noted) | STD-SAFETY-7 | Tool-classification argument added (§8.1). |

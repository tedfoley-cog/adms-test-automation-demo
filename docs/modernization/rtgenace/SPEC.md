# RTGENACE behavioural specification (v1.0)

**Status:** ported and verified. The port in `backend/app/rtgenace.py` matches the
legacy task on 69/69 corpus savecases ([TRACEABILITY.md](TRACEABILITY.md#current-parity-evidence)).
**Legacy source:** `legacy/habitat/src/ace_calc.f90` (program `RTGENACE`, subroutines
`RPTACE`, `ALLOCR`) and `legacy/habitat/src/hab_savecase.f90` (`HDB_READ_EXPORT`).
**Method:** the behaviour below was captured from the gfortran-built binary *before* the
port (69 goldens in `legacy/habitat/characterization/rtgenace/`), not taken from comments.

The requirement IDs (`RTG-*`) are defined in [`traceability.json`](traceability.json), the
single source of truth. [TRACEABILITY.md](TRACEABILITY.md) renders it with links to the
Fortran lines, the port and the tests. This document explains the behaviour; it does
not restate each requirement.

## 1. Purpose

Once per 4 s AGC cycle, RTGENACE computes the balancing area's Reporting ACE under
NERC BAL-001. It then splits the correction needed across the generating units on AGC,
as a change in MW setpoint for each unit. Off-line it runs as
`rtgenace <savecase-export>`. On the platform the same computation is bound to the
SCADAMOM clone.

## 2. Input: savecase export (`RTG-R01` to `RTG-R08`)

An ASCII export of the RTNET.EMS clone, read line by line (records separated by LF):

```text
* comment (any bytes)
CLONE    RTNET.EMS
SAVECASE RTNET_EMS_0742
RECORD FREQ
  AREA.CEDARVALLEY      59.968       60.000      -412.0    N    id actual_hz sched_hz bias(MW/0.1Hz) qual
RECORD TIELINE
  TIE.NORTH340           418.2          400.0        N          id actual_mw sched_mw qual
RECORD METERR
  AREA.CEDARVALLEY        2.5                                   id meter_error_mw
RECORD UNIT
  GEN.HARBOR1           212.0    120.0     260.0       6.0       0.45     T
                                                                id mw min max ramp_mw_per_min partf agc(T/F)
END
```
(Excerpt of `legacy/habitat/savecases/rtnet_ems_0742.export`; column notes added.)

- A `RECORD` line selects how the rows after it are read. Unknown kinds are skipped. `CLONE` and `TIMESTAMP` lines are ignored. Reading stops at `END`.
- Each table has a fixed size: 32 tie lines, 64 units, 256 feeders. One record too many refuses the whole export; it is never cut short.
- Errors: `IERR=1` if the file cannot be opened; `IERR=2` if a row cannot be read or a table overflows. Either one gives exit 3 (§5).
- Read but not used by RTGENACE: `FEEDER` rows (LOADSHED uses them), the FREQ quality flag, and the tie-line quality flags.

## 3. Computation

### 3.1 Reporting ACE (`RTG-C01`, `RPTACE`)

\[ ACE = (\textstyle\sum NI_a - \sum NI_s) - 10B(F_a - F_s) - I_{ME} \]

`B` is negative (MW/0.1 Hz), so under-frequency adds a positive bias term and makes ACE more negative.

### 3.2 Regulation allocation (`RTG-C02` to `RTG-C06`, `ALLOCR`)

```text
setpoint[i] = 0 for every unit row i
if |ACE| <= 5.0: return                                  # deadband, inclusive
pool = rows with agc == T and partf > 0
if sum(partf over pool) <= 0: return
for each row i in pool, in export order:
    share  = -ACE * partf[i] / sum(partf)
    share  = clip(share, -ramp[i]*4/60, +ramp[i]*4/60)    # ramp first
    target = mw[i] + share
    if target < min[i]: target = min[i]                  # then min
    if target > max[i]: target = max[i]                  # then max (wins if min > max)
    setpoint[i] = target - mw[i]
```

### 3.3 Legacy quirks deliberately preserved

The port reproduces these legacy behaviours as they are. Changing any of them is a
behaviour change and must go through `safety-critical-change`.

| Quirk | Consequence | Requirement |
|---|---|---|
| Limits are clipped after ramp | A unit that starts outside its limits is moved into them, even against ACE and faster than its ramp rate | `RTG-C05` |
| Min is clipped before max | If `min > max`, the target is `max` | `RTG-C05` |
| One setpoint per row | Duplicate unit names get separate setpoints | `RTG-C06` |
| `F12.4` output | A value 10⁷ MW or larger prints as `************` | `RTG-O01` |
| Inclusive deadband | `|ACE| = 5.0` gives no regulation | `RTG-C02` |

`/agc/dispatch` in `app/api.py` still uses `agc.allocate_regulation`, which returns a
dict keyed by unit name. It therefore assumes unit names are unique; RTGENACE does not.

## 4. Output (`RTG-O01`, `RTG-O02`)

```text
SAVECASE RTNET_EMS_0742
ACE_MW      -116.3462
SETPT    GEN.HARBOR1               0.4000
SETPT    GEN.HARBOR2               0.4000
SETPT    GEN.MESQUITE_CT           1.2000
SETPT    GEN.CEDAR_STM             0.0000
```

Fortran formats: `(A,A)`, `(A,F12.4)`, then `(A,A20,F12.4)` for each unit row.

| Exit | Meaning | stdout |
|---|---|---|
| 0 | report printed | the report |
| 2 | no path argument | `RTGENACE: usage: rtgenace <savecase-export>` |
| 3 | reader refused export | `RTGENACE: savecase read failed, ierr= 2` (`I2`) |

## 5. Numerical equivalence (`RTG-P01` to `RTG-P03`)

The legacy stores every value as REAL (binary32); the port computes in binary64. The two
are equivalent when:

1. the legacy and the port either both accept or both refuse the export;
2. they list the same unit rows in the same order;
3. `|ACE_legacy - ACE_port| <= ace_parity_bound(case)`, and every setpoint is within
   `setpoint_parity_bound(case, i, ACE)`. The bounds are derived per savecase from
   float32 representation and rounding error, weighted by how sensitive RPTACE and
   ALLOCR are to each input. There is no fixed tolerance. The worst corpus case uses
   99.0% of its bound, so the bound is tight.
4. When float32 alone could put ACE on either side of the 5 MW deadband, the printed
   legacy ACE decides (`legacy_setpoints_consistent`).

## 6. Acceptance gate

A change to RTGENACE, its port or its inputs is acceptable only if all of these pass:

- `pytest -m characterization`: 142 RTGENACE tests. The legacy binary must reproduce
  every golden, and the port must match every golden.
- `test_agc_invariants.py`:
  - the 1000-seed safety invariant (`RTG-C07`);
  - the 500-seed out-of-limit invariant;
  - the 500-savecase live fuzz against the gfortran binary.
- `test_rtgenace_edge_parity.py`: duplicate names, `F12.4` overflow, comment bytes, knife-edge cases.
- `python tools/build_traceability.py --check`: every requirement still resolves.

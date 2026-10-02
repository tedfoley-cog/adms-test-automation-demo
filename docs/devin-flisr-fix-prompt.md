# Devin prompt: fix the FLISR fault-location defect

Paste everything below the line into a new Devin session against
`tedfoley-cog/adms-test-automation-demo`. It is self-contained.

The repository's safety-critical-change skill lives at
`.agents/skills/safety-critical-change/SKILL.md` (found by searching `.agents/skills/`). No
`AGENTS.md`, `CONTRIBUTING.md`, or other `SKILL.md`/`*.skill.md` file in the repo mentions
"safety-critical". The only other skill, `.agents/skills/verification-console-gauntlet/SKILL.md`,
says it is not required for a single defect fix handled by safety-critical-change.

---

You are fixing a fault-location defect in the FLISR (Fault Location, Isolation and Service
Restoration) engine in `tedfoley-cog/adms-test-automation-demo`. This code commands breakers,
reclosers and sectionalizers, so the bar is evidence, not plausibility.

## Mandatory process

Before you edit anything under `backend/app/`, read
`.agents/skills/safety-critical-change/SKILL.md` and invoke the `safety-critical-change`
skill. Follow its process exactly as written and in its order: 1 Baseline, 2 Pin current
behaviour, 3 Reproduce, 4 Minimal fail-safe fix, 5 Prove it, 6 Pull request. Don't skip,
reorder, or loosen any step. Don't touch `backend/app/flisr.py` until step 3's failing test
exists and you have its failure output. If anything in this prompt conflicts with that skill,
the skill wins. Say so in the PR.

## 1. Context: the defect

`locate_fault` in `backend/app/flisr.py` (lines ~24–35) picks the faulted section by **list
position**, not by network topology:

```python
indicated = [section for section in feeder.sections if section.fault_indicator]
order = {section.mrid: index for index, section in enumerate(feeder.sections)}
last_indicated = max(indicated, key=lambda section: order[section.mrid])
index = order[last_indicated.mrid]
if index + 1 < len(feeder.sections):
    return feeder.sections[index + 1].mrid
return last_indicated.mrid
```

It takes the indicated section with the highest index in `feeder.sections` and returns the
next entry in the list. That only works when the list is in radial order along one main line.
On a branched feeder it breaks in two cases:

- a lateral tapped off the main line has its section listed later in `feeder_model.json`
  than the main-line sections, or
- the lateral's fault-passage indication (FPI) is the last one in the list.

In both cases, "next in the list" is a section on a different branch. `locate_fault` then
returns the wrong section, and `_isolation_switches` (same file) opens the wrong switches. It
only matches SCADA switches whose `to_node == section.from_node` or
`from_node == section.to_node`, which are the two endpoint nodes of the mislocated section. So
it isolates a healthy stretch of main line and leaves the actual faulted lateral connected.

Topology model (`backend/app/models.py`, `backend/app/network.py`):

- `Section` and `Switch` both carry `from_node`/`to_node`. Sections are joined *through*
  switches. For example, on Cedar Ridge: `SEC-1201-01` ends at `N-1201-1`, then `REC-1201-1`
  (`N-1201-1`→`N-1201-1A`), then `SEC-1201-02` starts at `N-1201-1A`.
- `feeder.source_node` is the root of the radial feeder.
- `network.adjacency(feeder)` builds node → `[(neighbour, element_mrid)]` over all sections
  and **closed** switches. `network.energised_nodes` and `network.sections_downstream_of` walk
  it.

A concrete failing shape, already confirmed against the current code: main line
`SRC -CB- BUS -[MAIN-1, FPI]- N1 -REC-M- N1M -[MAIN-2]- N2 -SW-M2- N2M -[MAIN-3]- N3`, and a
lateral tapped at `N1`: `N1 -SW-L- N1L -[LAT-1, FPI]- NL1 -SW-L2- NL1A -[LAT-2]- NL2`. With
sections listed as `[MAIN-1, LAT-1, MAIN-2, MAIN-3, LAT-2]`, `locate_fault` returns `MAIN-2`.
The correct answer is `LAT-2`. The plan would open `REC-M`/`SW-M2` on the healthy main line
and leave the faulted lateral connected.

## 2. Prove the bug first (skill step 3)

- Add a failing test to `backend/tests/test_flisr.py`, or to a new file such as
  `backend/tests/test_flisr_topology.py`. Use a **branched** feeder fixture built in code
  (`Feeder`/`Section`/`Switch` from `app.models`; don't edit `backend/data/feeder_model.json`).
  In the fixture, a lateral's section is listed **out of radial order** in `feeder.sections`.
- Assert `locate_fault` returns the topologically correct section. If it fits naturally, also
  assert the operational consequence: `build_plan(...).isolation` opens the switches bounding
  the real faulted section and does not open healthy main-line switches.
- Run it against the **unmodified** `flisr.py` and show that it fails. Commit the failing test
  on its own before the fix commit (`git log` should show test-then-fix). Keep the failing
  `pytest` output verbatim for the PR body.
- If you can't make it fail, the defect isn't confirmed. Report that and stop. Don't fix
  speculatively.

## 3. Fix requirements (skill step 4)

Make `locate_fault` topology-aware:

- Walk from `feeder.source_node` along `from_node`/`to_node` connectivity. Where it fits,
  reuse `backend/app/network.py` helpers such as `adjacency` and `energised_nodes`, and keep
  the change minimal. Two caveats:
  - Inside `build_plan`, `locate_fault` runs **after** the lockout device has opened (e.g.
    `CB-1201` is `open=True`). `adjacency` drops open switches, so walking it from the source
    as-is would see nothing past the lockout. Locate on the feeder's normal radial topology:
    in-feeder switches are traversable whatever their present `open` state.
  - Never traverse **tie** switches (`kind == "tie"` / `normal_open`). They lead onto the
    alternate feeder.
- Following the existing convention, the faulted section is the first non-indicated section
  downstream of the last indicated element on the indicated path. If the last indicated
  section is a radial end with nothing downstream, return that section. This matches today's
  tail behaviour.
- **Refuse rather than guess** when the indications are ambiguous. Ambiguous includes at
  least:
  - **Non-contiguous indicated path**: an indicated section whose upstream path back to the
    source passes through a non-indicated section (a gap).
  - **Indications on multiple branches**: two or more diverging indicated branches, where you
    can't tell which branch is faulted.
  - **Lone downstream indication**: an indicated section with no indicated upstream path back
    to the source.
  - **Fork after the last indication**: more than one non-indicated section directly
    downstream of the last indicated element. This also leaves the faulted section
    undetermined, so treat it the same way unless the skill review says otherwise.
- Refuse in the module's existing way. `FlisrError` ("Raised when the engine cannot build a
  defensible plan") is the error type. `None` currently means "no fault indication received;
  manual patrol required" in `build_plan`. Pick one, explain the choice in the PR, and make
  sure `build_plan` never issues isolation or restoration steps on ambiguous input. If you
  pick `None`, the plan note must not falsely claim that no indication was received.
- Change only what the failing test needs. No drive-by refactors, renames, formatting
  changes, or new dependencies.

## 4. Regression constraint

Behaviour on the existing Cedar Ridge feeder (`FDR-1201` in `backend/data/feeder_model.json`)
must not change:

- `test_locate_fault_picks_section_beyond_last_indication` must still pass unmodified. It
  asserts `locate_fault(feeder) == "SEC-1201-03"`.
- `test_build_plan_isolates_and_restores_tail` must still pass unmodified. It asserts
  isolation `{"SEC-SW-1201-1", "REC-1201-2"}` and `customers_restored == 341`.
- Every other existing test must pass, along with the step 2 `@pytest.mark.characterization`
  tests you add to pin the full current `build_plan` output (every isolation/restoration step,
  customer counts, transferred load, notes) for the inputs it already handles correctly.

## 5. Prove it, then open the PR (skill steps 5–6)

- Add the safety-invariant test the skill requires. A suitable rule: "the located section
  always lies on the indicated path's downstream frontier, and on any ambiguous indication set
  the engine refuses and issues no switching operation". Run it over at least 500 seeded
  `random` cases covering radial and branched topologies, with section lists shuffled.
- Run the full suite and lint:

  ```bash
  pip install -e './backend[dev]'
  pytest backend --cov=app --cov-branch --cov-report=term-missing
  make -C firmware test
  ruff check backend tools
  ```

  Everything must be green, and coverage of `app/flisr.py` must not drop from the step 1
  baseline.
- Open a pull request against `main`. Don't merge it. The description must explain the
  defect, the proof test (with the pre-fix failure output), and the ambiguity-refusal
  behaviour. Use the sections the skill requires:
  - **Defect**: one sentence in operational terms, plus the failure output.
  - **Root cause**: list-position ordering in `locate_fault`, `backend/app/flisr.py`
    lines ~24–35, and how it propagates through `_isolation_switches`.
  - **Fix**: the diff in pseudocode, plus what now happens on each kind of ambiguous input.
  - **Evidence**: number of pinned behaviours, number of invariant cases run, `flisr.py`
    coverage before → after.
  - **Blast radius**: which inputs change behaviour (branched or out-of-order feeders,
    ambiguous FPIs) and which provably don't (Cedar Ridge `FDR-1201` and the other
    characterized inputs).

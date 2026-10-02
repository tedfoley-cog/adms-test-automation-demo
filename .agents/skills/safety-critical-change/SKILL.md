---
name: safety-critical-change
description: Mandatory procedure for any change to control logic in this repo — FLISR, state estimation, AGC, savecase ingest (backend/app), protection firmware (firmware/src) or legacy Habitat tasks (legacy/habitat). Pins current behaviour, reproduces the defect with a failing test, applies the smallest fail-safe fix, proves a safety invariant and opens a PR with the evidence. Invoke before editing any of those paths, including bug fixes, refactors and ports.
---

# Safety-critical change

These modules command breakers, reclosers and generators. A wrong answer re-energises a fault
or moves a unit off schedule, so the bar is evidence, not plausibility. Do the steps in order
and do not edit production code before step 3.

## 1. Baseline

```bash
pip install -e './backend[dev]'
pytest backend --cov=app --cov-branch --cov-report=term-missing
make -C firmware test
```

Record the coverage of the module you will touch. Everything must be green before you start.

## 2. Pin current behaviour

Add `@pytest.mark.characterization` tests (C: a new `firmware/tests/test_*.c`) that pin what
the module does **today** on the inputs it already handles correctly — every plan step,
customer count and setpoint, not just one field. They must pass on the unmodified code and
must not change in step 4. If one has to change, stop and explain why in the PR.

## 3. Reproduce

Write the smallest test that fails on the current code and demonstrates the defect in
operational terms (e.g. "plan closes CB-1201 onto the faulted section"). Run it and keep the
failure output for the PR. If you cannot make it fail, the defect is not confirmed: report
that and stop — do not fix speculatively.

## 4. Minimal fail-safe fix

- Change only what the failing test needs. No drive-by refactors, renames or formatting.
- When the input is ambiguous or incomplete, refuse (raise the module's error type or return a
  manual-action plan). Never guess an operation on field equipment.
- No new dependencies.

## 5. Prove it

1. The step 3 test passes and every step 2 test passes unchanged.
2. Add a safety-invariant test that states the rule the fix protects (e.g. "no restoration
   step energises the faulted section") and check it over many generated inputs — a
   seeded `random` generator over radial and branched topologies, at least 500 cases. No new
   dependencies.
3. Re-run the step 1 commands plus `ruff check backend tools`. Coverage of the touched module
   must not drop.

## 6. Pull request

Open a PR against `main`; never merge it. The body must contain:

- **Defect** — one sentence in operational terms, plus the step 3 failure output.
- **Root cause** — the faulty assumption, with file and line.
- **Fix** — the diff in pseudocode and what now happens on ambiguous input.
- **Evidence** — pinned-behaviour count, invariant cases run, coverage before → after.
- **Blast radius** — which inputs change behaviour and which provably do not.

# Demo Cheat Sheet — ADMS/AEMS Test Automation &amp; Legacy Modernization

## Setup (do this before joining the call)
- [ ] Open the repo tab on `README.md` (flowchart renders at the top) and a fresh Devin session tab.
- [ ] Have the console open through Devin's live Desktop/Browser tab — it runs on Devin's machine, not yours.

## Demo Flow
1. Open the console on the Coverage tab: 35.6% line coverage, nine modules below target, the AGC service that replaces the legacy Fortran task at 0%. This is the day-zero state of a real grid-control portfolio, measured by gcov and coverage.py — not an estimate.
2. Switch to Legacy modernization: three Habitat-style Fortran tasks, `RTGENACE` already ported to `app/agc.py` but with zero characterization tests, `LOADSHED` not started. The parity table shows the savecase replay agreeing to 0.0062 MW — and the warning that with no characterization tests, that is one data point, not proof.
3. Prompt Devin: "Lift verification coverage on the Tier 1 gaps and modernize `RTGENACE`: characterize the Fortran behaviour first, port it, then prove parity on the savecase and refresh the console."
4. Talking point while it works: this is the automation-first QA mandate in practice — Devin measures, ranks by control function and release tier, generates tests for firmware *and* backend, and refuses to call a port done until the legacy behaviour is pinned.
5. Reload the console: coverage and tier gaps have moved, characterization tests are non-zero, and the parity table now stands on tests rather than a single replay.
6. Devin click-tests the console live in its own browser — filters, module drawer, backlog form validation, the modernization drill-down and the golden path — then reports verdicts and opens the PR.

# Demo Cheat Sheet — ADMS/AEMS Test Automation &amp; Legacy Modernization

## Setup (do this before joining the call)
- [ ] Open the repo tab on `README.md` (flowchart renders at the top) and a fresh Devin session tab.
- [ ] Have the console open through Devin's live Desktop/Browser tab — it runs on Devin's machine, not yours.

## Demo Flow
1. Open the console on the Coverage tab: 62.6% line coverage but 18 of 26 modules below target, 11 of them Tier 1 protection and control code, and the AGC service that replaces the legacy Fortran task at 0%. This is the day-zero state of a real grid-control portfolio, measured by gcov and coverage.py — not an estimate.
2. Switch to Real-time: the feeder IED (protection relay + PMU) runs on an emulated 168 MHz STM32F407 in Renode. Every task sits inside its cycle budget and every fault scenario trips correctly — but every scenario runs on a freshly booted relay at exactly 60 Hz, and six of eight C37.118.1 compliance tests are "not automated". That is the gap a real engineer worries about.
3. Switch to Legacy modernization: three Habitat-style Fortran tasks, `RTGENACE` already ported to `app/agc.py` but with zero characterization tests, `LOADSHED` not started. The parity table shows the savecase replay agreeing to 0.0062 MW — and the warning that with no characterization tests, that is one data point, not proof.
4. Prompt Devin: "Lift verification coverage on the Tier 1 gaps and modernize `RTGENACE`: characterize the Fortran behaviour first, port it, then prove parity on the savecase and refresh the console."
5. Talking point while it works: this is the automation-first QA mandate in practice — Devin measures, ranks by control function and release tier, generates tests for firmware *and* backend, and refuses to call a port done until the legacy behaviour is pinned.
6. Reload the console: coverage and tier gaps have moved, characterization tests are non-zero, and the parity table now stands on tests rather than a single replay.
7. Devin click-tests the console live in its own browser — filters, module drawer, backlog form validation, the modernization drill-down and the golden path — then reports verdicts and opens the PR.

## Embedded POC variant (GE Vernova "give Devin a small real-time app and a bug")
- Prompt: "Automate the C37.118.1 steady-state frequency-range test and a long-uptime soak for the feeder IED. Follow the safety-critical-change skill and prove the timing budgets still hold on the emulated STM32F407."
- Two latent defects are in the shipped firmware and no existing test reaches either. They are described only in the PR that built the IED (not in the repo), so a live session cannot read them here.
- What good looks like: failing tests first, minimal fixes, ≥500-case seeded invariants, the Real-time tab still green on cycle budgets, and a PR that states Renode is instruction-accurate, not silicon.

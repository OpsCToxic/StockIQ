---
description: Run the gate checks for a roadmap phase and report pass/fail with evidence
argument-hint: "<phase number>"
---
Run the gate for phase $ARGUMENTS as defined in docs/roadmap.md.

1. Run `make lint test` and `make gate PHASE=$ARGUMENTS`; capture results.
2. For gate criteria that need judgment or manual data (e.g. reconciliation to the real portfolio,
   spot-checking 20 attribution days, alert usefulness ratings), say exactly what Cameron needs to
   check or provide — don't mark them passed.
3. For phases touching analytics, ask the quant-reviewer subagent to review the phase's code.
4. Report: each criterion → pass / fail / needs Cameron, with evidence. Only update roadmap.md
   status when every criterion passes.

---
description: Review the current diff against architecture invariants and quant correctness
argument-hint: "[path or git range]"
---
Review $ARGUMENTS (default: `git diff` against main plus untracked files).

1. Run `python scripts/check_invariants.py`.
2. Use the architecture-reviewer subagent on the change.
3. If anything under src/stockiq/modules/, SQL touching time series, or event/lead-lag logic changed,
   also use the quant-reviewer subagent.
4. Merge the findings into one list ordered by severity, with file:line and the fix. Don't apply fixes
   unless asked.

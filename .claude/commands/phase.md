---
description: Show the current roadmap phase, what's done, and propose the next task
argument-hint: "[phase number]"
---
Read docs/roadmap.md and CLAUDE.md. Phase to inspect: $ARGUMENTS (default: the "Current phase" line).

1. List that phase's items with status, and its gate.
2. Check the repo (files, tests, migrations) to see whether items marked done really are, and whether
   any marked todo are already partly built. Note mismatches.
3. Propose the single next task: what it is, which files it touches, which skill/subagent applies,
   and how it will be tested. Don't start it until Cameron agrees.

#!/usr/bin/env python3
"""Automated part of each roadmap phase gate. Judgment-based criteria are listed, not faked."""

from __future__ import annotations

import subprocess
import sys

AUTOMATED: dict[int, list[list[str]]] = {
    0: [["python3", "scripts/check_invariants.py"]],
    2: [["python", "-m", "stockiq.graph.eval", "--min-precision", "0.90"]],
    5: [["pytest", "-q", "tests/pit"]],
    7: [["python", "-m", "stockiq.entities.eval", "--source", "social", "--min-precision", "0.90"]],
}
MANUAL: dict[int, list[str]] = {
    1: [
        "Look-through totals reconcile to within 1% of real portfolio value (compare with broker statement)."
    ],
    3: ["Spot-check 20 high-residual days: explanation cites a real, relevant item on most."],
    4: ["Fewer than ~3 urgent alerts/week at chosen thresholds; most rated useful."],
    6: ["Historical lead/lag results recorded for each smart-money signal type on your holdings."],
}


def main(phase: int) -> int:
    failed = False
    for cmd in AUTOMATED.get(phase, []):
        print("$", " ".join(cmd))
        failed |= subprocess.run(cmd).returncode != 0
    for item in MANUAL.get(phase, []):
        print(f"[needs Cameron] {item}")
    if phase not in AUTOMATED and phase not in MANUAL:
        print(f"No gate defined for phase {phase}.")
    print(
        "GATE:", "FAIL" if failed else ("PASS (automated part)" if phase in AUTOMATED else "manual")
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(int(sys.argv[1])))

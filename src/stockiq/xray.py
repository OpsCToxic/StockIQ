"""The exposure X-ray report: `python -m stockiq.xray [ISO_DATETIME]` (default: now).

Look-through exposure by company, industry and country, then concentration flags and the
Herfindahl index. The clock is read here, at the edge; everything below takes an explicit `as_of`.
"""

import sys
from datetime import UTC, datetime

from stockiq.core.db import get_engine
from stockiq.graph.exposure import Exposure, look_through
from stockiq.graph.report import render
from stockiq.modules.exposure.concentration import Concentration, concentration


def render_concentration(x: Exposure, c: Concentration) -> str:
    lines = ["", "Concentration (at or above 10% of your portfolio):"]
    if not c.flags:
        lines.append("  No single company, industry or country is at or above the threshold.")
    for f in c.flags:
        lines.append(f"  {f.kind:<9} {f.basis:<9} {f.name[:44]:<44} {f.share:>8.1%}")
    lines += ["", "Herfindahl index over companies (1.0 = one company, 1/n = n equal companies):"]
    for h in c.herfindahl:
        lines.append(
            f"  {h.basis:<9} HHI {h.hhi:.3f}   effective number of companies {h.effective_n:.1f}"
            f"   ({h.companies} companies, {h.covered_fraction:.0%} of portfolio value covered)"
        )
    lines += [
        "",
        "These describe what you hold at the dates shown. They are not predictions.",
    ]
    return "\n".join(lines)


def main(as_of: datetime) -> str:
    with get_engine().connect() as conn:
        x = look_through(conn, as_of)
    if not x.snapshot_as_of:
        return render(x)
    return render(x) + "\n" + render_concentration(x, concentration(x))


if __name__ == "__main__":
    when = datetime.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else datetime.now(UTC)
    print(main(when if when.tzinfo else when.replace(tzinfo=UTC)))

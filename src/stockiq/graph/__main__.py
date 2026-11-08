"""Print the look-through exposure: `python -m stockiq.graph [ISO_DATETIME]` (default: now)."""

import sys
from datetime import UTC, datetime

from stockiq.core.db import get_engine
from stockiq.graph.exposure import look_through
from stockiq.graph.report import render

if __name__ == "__main__":
    when = datetime.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else datetime.now(UTC)
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    with get_engine().connect() as conn:
        print(render(look_through(conn, when)))

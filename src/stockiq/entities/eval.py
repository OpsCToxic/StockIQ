"""Entity-resolution evaluation on a labelled sample (the Phase 2 gate).

    python -m stockiq.entities.eval build-gold --source etf_holdings [--n 150]
    python -m stockiq.entities.eval --source etf_holdings --min-precision 0.90

`build-gold` samples equity lines from stored fund filings and labels each by a path that does not
use the resolver: CUSIP -> ticker through OpenFIGI, then ticker -> SEC company. These are silver
labels: a person should look over `tests/gold/resolution/etf_holdings.csv` and correct any row
(set `reviewed` to yes). Rows with no expected company are left out of the precision figure.

The evaluation resolves each mention with taught and reviewed aliases switched off, so a mention
cannot be answered by a decision made on that very mention.

Precision is correct links over all links the resolver made (provisional links count: they are in
the graph). Recall is correct links over labelled rows.
"""

import argparse
import asyncio
import csv
import random
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Connection, text

from stockiq.entities.resolver import Mention, resolve

GOLD_DIR = Path(__file__).parents[3] / "tests" / "gold" / "resolution"
FIELDS = [
    "cusip", "isin", "lei", "name", "expected_cik", "expected_name",
    "label_source", "note", "reviewed",
]  # fmt: skip


@dataclass
class Scored:
    row: dict[str, str]
    entity_cik: str | None
    entity_name: str | None
    confidence: float
    method: str
    entity_id: int | None = None

    @property
    def linked(self) -> bool:
        # By entity id, not CIK: a link to a fund or private entity (no CIK) is still a link, and a
        # wrong one must count against precision rather than drop out of the denominator.
        return self.entity_id is not None or self.entity_cik is not None

    @property
    def correct(self) -> bool:
        return self.linked and self.entity_cik == self.row["expected_cik"]


def gold_path(source: str) -> Path:
    return GOLD_DIR / f"{source}.csv"


def read_gold(source: str) -> list[dict[str, str]]:
    with gold_path(source).open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def score(conn: Connection, rows: list[dict[str, str]], as_of: datetime) -> list[Scored]:
    out = []
    for row in rows:
        mention = Mention(
            name=row["name"] or None,
            cusip=row["cusip"] or None,
            isin=row["isin"] or None,
            lei=row["lei"] or None,
        )
        r = resolve(conn, mention, as_of, use_learned=False)
        cik = name = None
        if r.accepted and r.entity_id is not None:
            e = conn.execute(
                text("SELECT cik, name FROM entity WHERE id = :i"), {"i": r.entity_id}
            ).one()
            cik, name = e.cik, e.name
        out.append(
            Scored(
                row, cik, name, float(r.confidence), r.method, r.entity_id if r.accepted else None
            )
        )
    return out


def wilson_lower(correct: int, n: int, z: float = 1.96) -> float:
    """95% lower confidence bound for a proportion. 127 of 127 is about 97%, not a certain 100%."""
    if n == 0:
        return 0.0
    p = correct / n
    centre = p + z * z / (2 * n)
    margin = z * ((p * (1 - p) + z * z / (4 * n)) / n) ** 0.5
    return float((centre - margin) / (1 + z * z / n))


def summarise(scored: list[Scored]) -> dict[str, float]:
    labelled = [s for s in scored if s.row["expected_cik"]]
    linked = [s for s in labelled if s.linked]
    correct = [s for s in linked if s.correct]
    return {
        "labelled": len(labelled),
        "linked": len(linked),
        "correct": len(correct),
        "precision": len(correct) / len(linked) if linked else 0.0,
        "precision_low": wilson_lower(len(correct), len(linked)),
        "recall": len(correct) / len(labelled) if labelled else 0.0,
    }


def unreviewed_scored(scored: list[Scored]) -> int:
    """Scored rows (those with an expected company) that no person has marked reviewed."""
    return sum(1 for s in scored if s.row["expected_cik"] and s.row["reviewed"].lower() != "yes")


def report(scored: list[Scored]) -> str:
    s = summarise(scored)
    lines = [
        f"labelled rows {s['labelled']:.0f}, linked {s['linked']:.0f}, correct {s['correct']:.0f}",
        f"precision {s['precision']:.1%} (95% lower bound {s['precision_low']:.1%})   "
        f"recall {s['recall']:.1%} (over labelled rows only)",
    ]
    by_method: Counter[str] = Counter()
    wrong_by_method: Counter[str] = Counter()
    for x in scored:
        if x.row["expected_cik"] and x.linked:
            by_method[x.method] += 1
            wrong_by_method[x.method] += 0 if x.correct else 1
    for method, n in by_method.most_common():
        lines.append(f"  {method:<28} linked {n:>4}   wrong {wrong_by_method[method]:>3}")
    wrong = [x for x in scored if x.row["expected_cik"] and x.linked and not x.correct]
    if wrong:
        lines.append("Wrong links:")
        for x in wrong:
            lines.append(
                f"  {x.row['name']!r} -> {x.entity_name!r} ({x.method} {x.confidence:.2f}); "
                f"expected {x.row['expected_name']!r}"
            )
    unlabelled = sum(1 for x in scored if not x.row["expected_cik"])
    if unlabelled:
        lines.append(f"{unlabelled} rows have no expected company and are not scored.")
    unreviewed = sum(1 for x in scored if x.row["reviewed"].lower() != "yes")
    lines.append(f"{unreviewed} of {len(scored)} labels have not been reviewed by a person.")
    return "\n".join(lines)


async def _label_rows(cusips: list[str], api_key: str) -> dict[str, tuple[str, str] | None]:
    """CUSIP -> (ticker, name) from OpenFIGI's US composite listing; None if not exactly one."""
    from stockiq.connectors.openfigi.client import MAPPING_URL, figi_client

    client, max_jobs = figi_client(api_key)
    found: dict[str, tuple[str, str] | None] = {}
    try:
        for i in range(0, len(cusips), max_jobs):
            batch = cusips[i : i + max_jobs]
            jobs = [{"idType": "ID_CUSIP", "idValue": c, "exchCode": "US"} for c in batch]
            response = await client.request("POST", MAPPING_URL, json=jobs)
            for cusip, result in zip(batch, response.json(), strict=True):
                rows = [r for r in result.get("data", []) if r.get("exchCode") == "US"]
                composites = {r.get("compositeFIGI") for r in rows if r.get("compositeFIGI")}
                found[cusip] = (
                    (rows[0]["ticker"], rows[0].get("name", "")) if len(composites) == 1 else None
                )
    finally:
        await client.aclose()
    return found


def build_gold(conn: Connection, source: str, n: int, api_key: str) -> int:
    if source != "etf_holdings":
        raise SystemExit(f"unknown source {source!r}")
    lines = conn.execute(
        text(
            """
            SELECT DISTINCT ON (cusip) cusip, isin, lei, name FROM fund_holding
            WHERE asset_cat = 'EC' AND payoff_profile = 'Long' AND cusip IS NOT NULL
              AND cusip NOT IN ('N/A', '000000000') AND name <> 'N/A'
            ORDER BY cusip, as_of DESC
            """
        )
    ).all()
    sample = random.Random(2026).sample(lines, min(n, len(lines)))  # fixed seed: reproducible  # noqa: S311 - reproducible sample, not security
    labels = asyncio.run(_label_rows([r.cusip for r in sample], api_key))
    out = []
    for r in sorted(sample, key=lambda r: r.cusip):
        ticker_name = labels.get(r.cusip)
        cik = ename = ""
        note = ""
        if ticker_name is None:
            note = "OpenFIGI gave no single US listing"
        else:
            ticker = ticker_name[0].replace("/", "-")
            ids = conn.execute(
                text(
                    "SELECT DISTINCT e.cik, e.name FROM entity_alias a JOIN entity e "
                    "ON e.id = a.entity_id WHERE a.kind = 'ticker' AND a.alias = :t "
                    "AND a.valid_to IS NULL AND e.type = 'company' AND e.cik IS NOT NULL"
                ),
                {"t": ticker},
            ).all()
            if len(ids) == 1:
                cik, ename = ids[0].cik, ids[0].name
            else:
                note = f"ticker {ticker} matches {len(ids)} SEC companies"
        out.append(
            {
                "cusip": r.cusip, "isin": r.isin or "", "lei": r.lei or "", "name": r.name,
                "expected_cik": cik, "expected_name": ename,
                "label_source": "openfigi_cusip_to_ticker_to_sec", "note": note, "reviewed": "",
            }
        )  # fmt: skip
    GOLD_DIR.mkdir(parents=True, exist_ok=True)
    with gold_path(source).open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(out)
    return len(out)


def main(argv: list[str]) -> int:
    from stockiq.core.config import get_settings
    from stockiq.core.db import get_engine

    ap = argparse.ArgumentParser(prog="stockiq.entities.eval")
    ap.add_argument("command", nargs="?", choices=["build-gold"])
    ap.add_argument("--source", required=True)
    ap.add_argument("--n", type=int, default=150)
    ap.add_argument("--min-precision", type=float, default=0.90)
    ap.add_argument(
        "--allow-unreviewed",
        action="store_true",
        help="development only: let the gate pass while scored labels lack a person's review",
    )
    args = ap.parse_args(argv)
    if args.command == "build-gold":
        key = get_settings().openfigi_api_key.get_secret_value()
        with get_engine().connect() as conn:
            count = build_gold(conn, args.source, args.n, key)
        print(f"wrote {count} rows to {gold_path(args.source)}; review them and mark reviewed=yes")
        return 0
    if not gold_path(args.source).exists():
        print(f"no gold file {gold_path(args.source)}; run build-gold first")
        return 1
    rows = read_gold(args.source)
    with get_engine().connect() as conn:
        scored = score(conn, rows, datetime.now(UTC))
    print(report(scored))
    precision = summarise(scored)["precision"]
    if precision < args.min_precision:
        print(f"GATE FAIL: precision {precision:.1%} is below {args.min_precision:.0%}")
        return 1
    unreviewed = unreviewed_scored(scored)
    if unreviewed and not args.allow_unreviewed:
        # Silver labels only: passing here would mean agreeing with ourselves.
        print(
            f"GATE UNVERIFIED: precision {precision:.1%} meets {args.min_precision:.0%}, but "
            f"{unreviewed} scored labels have not been reviewed by a person (reviewed=yes)."
        )
        return 1
    print(f"GATE PASS: precision {precision:.1%} >= {args.min_precision:.0%}, labels reviewed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

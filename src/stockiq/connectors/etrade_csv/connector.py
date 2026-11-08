"""Imports an E*TRADE "Portfolio > Download" positions CSV.

The file has several sections (account summary, positions, a CASH row, a TOTAL row, and a
"Generated at ..." footer). Positions are stored as of the footer time. The import refuses a file
whose positions plus cash do not add up to the file's own TOTAL value, and refuses symbols that do
not map to exactly one entity, rather than loading a partial portfolio.

The export has no per-lot detail and no account number; the account is named by the caller.
"""

import csv
import hashlib
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, text

from stockiq.connectors.base import BaseConnector, Cursor, RawPayload, StoredPayload
from stockiq.connectors.etrade_csv.models import CsvExport, CsvPosition, CsvRecord
from stockiq.entities.resolver import Mention, Resolution, resolve

BROKER = "etrade"
NY = ZoneInfo("America/New_York")
HEADER_PREFIX = "Symbol,Last Price"
TOLERANCE = Decimal("0.05")


def _num(value: str) -> Decimal:
    try:
        return Decimal(value.strip() or "0")
    except InvalidOperation as e:
        raise ValueError(f"not a number: {value!r}") from e


def parse_export(body: bytes, account_name: str | None = None) -> CsvExport:
    text_ = body.decode("utf-8-sig")
    lines = text_.splitlines()

    generated_at = None
    for line in lines:
        if line.startswith("Generated at "):
            stamp = line.removeprefix("Generated at ").removesuffix(" ET").strip()
            generated_at = datetime.strptime(stamp, "%b %d %Y %I:%M %p").replace(tzinfo=NY)
    if generated_at is None:
        raise ValueError("no 'Generated at ...' footer; cannot tell when this snapshot was taken")

    header_at = next((i for i, ln in enumerate(lines) if ln.startswith(HEADER_PREFIX)), None)
    if header_at is None:
        raise ValueError("no positions table found (expected a 'Symbol,Last Price $,...' header)")
    header = next(csv.reader([lines[header_at]]))
    col = {name.strip(): i for i, name in enumerate(header)}
    for needed in ("Quantity", "Price Paid $", "Total Gain $", "Value $"):
        if needed not in col:
            raise ValueError(f"positions table is missing the {needed!r} column")

    positions: list[CsvPosition] = []
    cash = Decimal("0")
    total_value: Decimal | None = None
    for row in csv.reader(lines[header_at + 1 :]):
        if not row or not row[0].strip():
            if positions or total_value is not None:
                break  # blank line ends the table
            continue
        symbol = row[0].strip().upper()
        if symbol == "TOTAL":
            total_value = _num(row[col["Value $"]])
        elif symbol == "CASH":
            cash = _num(row[col["Value $"]])
        else:
            positions.append(
                CsvPosition(
                    symbol=symbol,
                    qty=_num(row[col["Quantity"]]),
                    price_paid=_num(row[col["Price Paid $"]]),
                    value=_num(row[col["Value $"]]),
                    total_gain=_num(row[col["Total Gain $"]]),
                )
            )
    if total_value is None:
        raise ValueError("no TOTAL row; cannot check the file adds up")

    summed = sum((p.value for p in positions), Decimal("0")) + cash
    if abs(summed - total_value) > TOLERANCE:
        raise ValueError(f"positions + cash = {summed} but the file's TOTAL is {total_value}")

    if account_name is None:
        summary = next(csv.reader([lines[lines.index("Account Summary") + 2]]))
        account_name = summary[0]
    return CsvExport(
        generated_at=generated_at,
        account_name=account_name,
        positions=positions,
        cash=cash,
        total_value=total_value,
    )


class EtradeCsvConnector(BaseConnector[CsvRecord]):
    name = "etrade_csv"
    schedule = "batch"

    def __init__(self, path: Path, account_name: str | None = None) -> None:
        self._path = path
        self._account_name = account_name
        self.imported: CsvExport | None = None
        self.unresolved: list[tuple[Mention, Resolution]] = []

    async def fetch(self, since: Cursor) -> tuple[list[RawPayload], Cursor]:
        body = self._path.read_bytes()
        export = parse_export(body, self._account_name)  # fail before anything is stored

        digest = hashlib.sha256(body).hexdigest()[:16]
        raw = RawPayload(
            source_id=f"{export.generated_at:%Y%m%dT%H%M}-{digest}",
            ext="csv",
            body=body,
            fetched_at=datetime.now(NY),
            published_at=export.generated_at,
            kind="etrade_positions_csv",
        )
        return [raw], {"last_file": self._path.name}

    def parse(self, raw: RawPayload) -> list[CsvRecord]:
        return [parse_export(raw.body, self._account_name)]

    def upsert(self, conn: Connection, stored: StoredPayload, records: list[CsvRecord]) -> None:
        (export,) = records
        as_of = export.generated_at
        known_at = stored.raw.fetched_at  # when StockIQ got the file; never earlier than as_of

        account_id = conn.execute(
            text(
                """
                INSERT INTO account (broker, name) VALUES (:b, :n)
                ON CONFLICT (broker, name) DO UPDATE SET name = EXCLUDED.name
                RETURNING id
                """
            ),
            {"b": BROKER, "n": export.account_name},
        ).scalar_one()

        resolved: dict[str, int] = {}
        self.unresolved = []
        for pos in export.positions:
            mention = Mention(ticker=pos.symbol)
            result = resolve(conn, mention, known_at)
            if result.accepted and result.entity_id is not None:
                resolved[pos.symbol] = result.entity_id
            else:
                self.unresolved.append((mention, result))
        if self.unresolved:
            # A partial portfolio would be wrong, so nothing is imported. The caller queues these
            # for review (this transaction rolls back) so they can be fixed and re-imported.
            names = "; ".join(f"{m.ticker}: {r.method}" for m, r in self.unresolved)
            raise ValueError(
                f"cannot import, unresolved symbols: {names}. They are queued for review: "
                "python -m stockiq.entities.review list"
            )
        by_entity: dict[int, list[str]] = {}
        for symbol, entity_id in resolved.items():
            by_entity.setdefault(entity_id, []).append(symbol)
        clashes = [syms for syms in by_entity.values() if len(syms) > 1]
        if clashes:
            # holding is one row per entity (ADR 0006); two classes would overwrite each other.
            raise ValueError(f"cannot import, several symbols map to one company: {clashes}")

        conn.execute(
            text(
                """
                INSERT INTO holding
                    (account_id, security_id, as_of, qty, cost_basis, ticker, market_value,
                     known_at, doc_id)
                VALUES (:a, :s, :as_of, :qty, :cost, :ticker, :mv, :known, :doc)
                ON CONFLICT (account_id, security_id, as_of) DO UPDATE
                  SET qty = EXCLUDED.qty, cost_basis = EXCLUDED.cost_basis,
                      ticker = EXCLUDED.ticker, market_value = EXCLUDED.market_value
                """
            ),
            [
                {
                    "a": account_id,
                    "s": resolved[p.symbol],
                    "as_of": as_of,
                    "qty": p.qty,
                    "cost": p.cost_basis,
                    "ticker": p.symbol,
                    "mv": p.value,
                    "known": known_at,
                    "doc": stored.doc_id,
                }
                for p in export.positions
            ],
        )
        conn.execute(
            text(
                """
                INSERT INTO cash_balance (account_id, as_of, amount, known_at, doc_id)
                VALUES (:a, :as_of, :amt, :known, :doc)
                ON CONFLICT (account_id, as_of) DO UPDATE SET amount = EXCLUDED.amount
                """
            ),
            {
                "a": account_id,
                "as_of": as_of,
                "amt": export.cash,
                "known": known_at,
                "doc": stored.doc_id,
            },
        )
        self.imported = export

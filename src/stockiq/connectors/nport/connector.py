"""SEC Form N-PORT fund holdings, for ETF look-through.

Discovery uses EDGAR's per-series Atom feed (`browse-edgar ... CIK=<series id>&type=NPORT-P&
output=atom`); each filing's `primary_doc.xml` is stored raw, then parsed. Public N-PORT data is
quarterly with about a 60-day lag, so `known_at` is the filing date, never the report date.

Every reported line is kept in `fund_holding`. Resolved equity lines also become CONTAINS edges,
aggregated per constituent company, each with evidence rows quoting the filed XML (invariant 1).
Unresolved lines stay visible as unresolved exposure instead of being guessed.
"""

import re
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from xml.etree.ElementTree import Element
from zoneinfo import ZoneInfo

from defusedxml import ElementTree
from sqlalchemy import Connection, text

from stockiq.connectors.base import BaseConnector, Cursor, RawPayload, StoredPayload
from stockiq.connectors.nport.models import NportHolding, NportReport
from stockiq.connectors.sec_tickers.client import sec_client
from stockiq.core.config import Settings
from stockiq.entities.names import ensure_name_aliases
from stockiq.entities.resolver import ACCEPT, LEARNED_SOURCE, Mention, resolve
from stockiq.entities.review import enqueue

NY = ZoneInfo("America/New_York")
BROWSE_URL = "https://www.sec.gov/cgi-bin/browse-edgar"
KIND_FILING = "nport_p"
KIND_INDEX = "nport_index"
NS = "{http://www.sec.gov/edgar/nport}"
ATOM = "{http://www.w3.org/2005/Atom}"
EQUITY_CATS = {"EC", "EP"}
RATE_WORDS = re.compile(r"sofr|libor|fed ?funds|overnight|interest rate|euribor|sonia", re.I)


def _dec(el: Element | None, tag: str) -> Decimal | None:
    if el is None:
        return None
    value = el.findtext(NS + tag)
    return Decimal(value) if value not in (None, "") else None


def _parse_swap(el: Element) -> tuple[str | None, Decimal | None, str | None]:
    """Reference identifier, notional and direction of a swap line, else all None."""
    swap = el.find(f"{NS}derivativeInfo/{NS}swapDeriv")
    if swap is None:
        return None, None, None
    ref = swap.findtext(f"{NS}descRefInstrmnt/{NS}indexBasketInfo/{NS}indexIdentifier")
    notional = _dec(swap, "notionalAmt")
    recv = swap.find(f"{NS}floatingRecDesc")
    pay = swap.find(f"{NS}floatingPmntDesc")
    recv_text = (recv.get("floatingRtIndex") or "") if recv is not None else ""
    pay_text = (pay.get("floatingRtIndex") or "") if pay is not None else ""
    if not ref or ref.upper() == "N/A" or notional is None or not (recv_text or pay_text):
        return None, None, None
    # The fund receives the reference's return unless the receive leg is the rate leg.
    short = bool(RATE_WORDS.search(recv_text)) and not RATE_WORDS.search(pay_text)
    return ref.strip().upper(), notional, "short" if short else "long"


def parse_report(body: bytes, accession: str, known_at: datetime) -> NportReport:
    root = ElementTree.fromstring(body)
    gen = root.find(f"{NS}formData/{NS}genInfo")
    if gen is None:
        raise ValueError("not an N-PORT filing: no genInfo")
    # Verbatim spans: ElementTree drops the original text, so slice it out in the same order.
    spans = re.findall(r"<invstOrSec>.*?</invstOrSec>", body.decode("utf-8"), flags=re.S)
    holdings = []
    for seq, el in enumerate(root.iter(f"{NS}invstOrSec")):
        isin = el.find(f"{NS}identifiers/{NS}isin")
        swap_ref, notional, direction = _parse_swap(el)
        holdings.append(
            NportHolding(
                seq=seq,
                name=el.findtext(NS + "name") or "",
                title=el.findtext(NS + "title"),
                cusip=el.findtext(NS + "cusip"),
                isin=isin.get("value") if isin is not None else None,
                lei=el.findtext(NS + "lei"),
                asset_cat=el.findtext(NS + "assetCat"),
                payoff_profile=el.findtext(NS + "payoffProfile"),
                country=el.findtext(NS + "invCountry"),
                balance=_dec(el, "balance"),
                val_usd=_dec(el, "valUSD"),
                pct_val=_dec(el, "pctVal"),
                swap_ref=swap_ref,
                notional=notional,
                swap_direction=direction,
                span_text=spans[seq],
            )
        )
    report_date = date.fromisoformat(gen.findtext(NS + "repPdDate") or "")
    # Public N-PORT data is released about 60 days after the report date, and under the 2024
    # amendments a monthly report can be filed earlier than it is released. Never treat it as
    # known before report date + 60 days, whatever the feed's filing date says.
    release = datetime.combine(report_date + timedelta(days=60), time(0, 0), tzinfo=NY)
    return NportReport(
        series_id=gen.findtext(NS + "seriesId") or "",
        series_name=gen.findtext(NS + "seriesName") or "",
        filer_cik=gen.findtext(NS + "regCik") or "",
        report_date=report_date,
        known_at=max(known_at, release),
        net_assets=_dec(root.find(f"{NS}formData/{NS}fundInfo"), "netAssets"),
        total_assets=_dec(root.find(f"{NS}formData/{NS}fundInfo"), "totAssets"),
        accession=accession,
        holdings=holdings,
    )


def parse_feed(body: bytes) -> list[dict[str, Any]]:
    """Filings in a series' Atom feed, newest first: accession, filing date, folder URL."""
    root = ElementTree.fromstring(body)
    filings = []
    for entry in root.iter(f"{ATOM}entry"):
        content = entry.find(f"{ATOM}content")
        if content is None:
            continue
        accession = content.findtext(f"{ATOM}accession-number")
        filed = content.findtext(f"{ATOM}filing-date")
        href = content.findtext(f"{ATOM}filing-href")
        if accession and filed and href:
            filings.append(
                {
                    "accession": accession,
                    "filed": date.fromisoformat(filed),
                    "folder": href.rsplit("/", 1)[0],
                }
            )
    return filings


def _public_at(filed: date) -> datetime:
    # The feed gives a filing date, not a time: treat it as public from the next midnight.
    return datetime.combine(filed + timedelta(days=1), time(0, 0), tzinfo=NY)


class NportConnector(BaseConnector[NportReport]):
    name = "nport"
    schedule = "batch"

    def __init__(
        self,
        client: Any,
        series_ids: list[str],
        max_filings: int = 1,
        now: datetime | None = None,
    ) -> None:
        self._client = client
        self._series = sorted(set(series_ids))
        self._max = max_filings
        self._now = now

    @classmethod
    def from_settings(
        cls, settings: Settings, series_ids: list[str], max_filings: int = 1
    ) -> "NportConnector":
        return cls(sec_client(settings.sec_user_agent), series_ids, max_filings)

    async def fetch(self, since: Cursor) -> tuple[list[RawPayload], Cursor]:
        now = self._now or datetime.now(UTC)
        seen: set[str] = set(since.get("seen", []))
        payloads: list[RawPayload] = []
        for series in self._series:
            feed = await self._client.get(
                BROWSE_URL,
                params={
                    "action": "getcompany",
                    "CIK": series,
                    "type": "NPORT-P",
                    "dateb": "",
                    "owner": "include",
                    "count": "10",
                    "output": "atom",
                },
            )
            payloads.append(
                RawPayload(
                    source_id=f"feed-{series}-{now:%Y-%m-%d}",
                    ext="xml",
                    body=feed.content,
                    fetched_at=now,
                    url=BROWSE_URL,
                    published_at=now,
                    kind=KIND_INDEX,
                )
            )
            for filing in parse_feed(feed.content)[: self._max]:
                if filing["accession"] in seen:
                    continue
                url = f"{filing['folder']}/primary_doc.xml"
                doc = await self._client.get(url)
                payloads.append(
                    RawPayload(
                        source_id=filing["accession"],
                        ext="xml",
                        body=doc.content,
                        fetched_at=now,
                        url=url,
                        published_at=_public_at(filing["filed"]),
                        kind=KIND_FILING,
                    )
                )
                seen.add(filing["accession"])
        return payloads, {"seen": sorted(seen)}

    def parse(self, raw: RawPayload) -> list[NportReport]:
        if raw.kind == KIND_INDEX:
            return []
        assert raw.published_at is not None
        return [parse_report(raw.body, raw.source_id, raw.published_at)]

    def upsert(self, conn: Connection, stored: StoredPayload, records: list[NportReport]) -> None:
        for report in records:
            self._upsert_report(conn, stored, report)

    def _upsert_report(self, conn: Connection, stored: StoredPayload, rpt: NportReport) -> None:
        fund_id = conn.execute(
            text("SELECT id FROM entity WHERE series_id = :s AND type = 'fund'"),
            {"s": rpt.series_id},
        ).scalar_one_or_none()
        if fund_id is None:
            raise ValueError(f"no fund entity for series {rpt.series_id}; run sec_tickers first")
        # The SEC fund file has no names; take the series name where only a ticker stands in.
        conn.execute(
            text(
                """
                UPDATE entity SET name = :n
                WHERE id = :id AND name IN (
                    SELECT alias FROM entity_alias WHERE entity_id = :id AND kind = 'ticker')
                """
            ),
            {"n": rpt.series_name.title(), "id": fund_id},
        )
        ensure_name_aliases(conn)

        conn.execute(
            text(
                """
                INSERT INTO fund_report
                    (doc_id, fund_id, as_of, known_at, net_assets, total_assets)
                VALUES (:doc, :f, :d, :k, :na, :ta)
                ON CONFLICT (doc_id) DO UPDATE SET net_assets = EXCLUDED.net_assets,
                    total_assets = EXCLUDED.total_assets
                """
            ),
            {
                "doc": stored.doc_id,
                "f": fund_id,
                "d": rpt.report_date,
                "k": rpt.known_at,
                "na": rpt.net_assets,
                "ta": rpt.total_assets,
            },
        )
        resolved = [(h, *self._resolve(conn, h, rpt.known_at, stored.doc_id)) for h in rpt.holdings]
        conn.execute(
            text(
                """
                INSERT INTO fund_holding
                    (fund_id, as_of, known_at, doc_id, seq, name, title, cusip, isin, lei,
                     asset_cat, payoff_profile, country, balance, val_usd, pct_val,
                     swap_ref, notional, swap_direction,
                     constituent_id, match_method, match_confidence)
                VALUES
                    (:fund, :as_of, :known, :doc, :seq, :name, :title, :cusip, :isin, :lei,
                     :cat, :payoff, :country, :bal, :val, :pct, :sref, :notl, :sdir,
                     :cid, :method, :conf)
                ON CONFLICT (doc_id, seq) DO UPDATE SET
                    constituent_id = EXCLUDED.constituent_id,
                    match_method = EXCLUDED.match_method,
                    match_confidence = EXCLUDED.match_confidence
                """
            ),
            [
                {
                    "fund": fund_id,
                    "as_of": rpt.report_date,
                    "known": rpt.known_at,
                    "doc": stored.doc_id,
                    "seq": h.seq,
                    "name": h.name,
                    "title": h.title,
                    "cusip": h.cusip,
                    "isin": h.isin,
                    "lei": h.lei,
                    "cat": h.asset_cat,
                    "payoff": h.payoff_profile,
                    "country": h.country,
                    "bal": h.balance,
                    "val": h.val_usd,
                    "pct": h.pct_val,
                    "sref": h.swap_ref,
                    "notl": h.notional,
                    "sdir": h.swap_direction,
                    "cid": cid,
                    "method": method,
                    "conf": conf,
                }
                for h, cid, method, conf in resolved
            ],
        )
        self._remember_identifiers(conn, resolved, rpt.known_at)
        self._write_edges(conn, stored, rpt, fund_id, resolved)

    def _resolve(
        self, conn: Connection, h: NportHolding, at: datetime, doc_id: int
    ) -> tuple[int | None, str | None, Decimal | None]:
        """Resolve one reported line. Swaps resolve by their reference ticker; everything else by
        identifier, then name. Weak matches are queued for review, equity lines only (cash and
        T-bills are not worth a human's time)."""
        name = None if h.name.strip().upper() in ("", "N/A") else h.name
        if h.swap_ref:
            mention = Mention(ticker=h.swap_ref)
        else:
            mention = Mention(name=name, cusip=h.cusip, isin=h.isin, lei=h.lei)
        result = resolve(conn, mention, at)
        is_equity = h.asset_cat in EQUITY_CATS and h.payoff_profile == "Long"
        # An equity line nothing matched still goes to the queue (no candidates), so a
        # reviewer can find a renamed company by hand instead of it staying unresolved.
        if (result.needs_review or not result.accepted) and (is_equity or h.swap_ref):
            enqueue(conn, "nport", f"doc:{doc_id}:seq:{h.seq}", mention, result)
        if result.accepted:
            return result.entity_id, result.method, result.confidence
        return None, None, None

    def _remember_identifiers(
        self,
        conn: Connection,
        resolved: list[tuple[NportHolding, int | None, str | None, Decimal | None]],
        at: datetime,
    ) -> None:
        """A confident (>= 0.9) name match teaches us the CUSIP/ISIN, so the next run matches by
        identifier. A provisional fuzzy match teaches nothing until a reviewer accepts it."""
        rows = []
        for h, cid, method, conf in resolved:
            if cid is None or h.swap_ref or conf is None or conf < ACCEPT:
                continue
            if method not in ("exact_name", "identifier:cusip:learned", "identifier:isin:learned"):
                continue
            for kind, value in (("cusip", h.cusip), ("isin", h.isin)):
                if value:
                    rows.append({"e": cid, "a": value, "k": kind, "at": at})
        if rows:
            conn.execute(
                text(
                    """
                    INSERT INTO entity_alias (entity_id, alias, kind, source, valid_from, known_at)
                    VALUES (:e, :a, :k, :src, :at, :at)
                    ON CONFLICT (entity_id, alias, kind, valid_from) DO NOTHING
                    """
                ),
                [{**r, "src": LEARNED_SOURCE} for r in rows],
            )

    def _write_synthetic_edges(
        self,
        conn: Connection,
        stored: StoredPayload,
        rpt: NportReport,
        fund_id: int,
        resolved: list[tuple[NportHolding, int | None, str | None, Decimal | None]],
        valid_from: datetime,
    ) -> None:
        """Swap notional over net assets, signed, per reference company."""
        if not rpt.net_assets or rpt.net_assets <= 0:
            return
        by_company: dict[int, list[tuple[NportHolding, Decimal]]] = {}
        for h, cid, _, conf in resolved:
            if cid is not None and conf is not None and h.swap_ref and h.notional is not None:
                by_company.setdefault(cid, []).append((h, conf))
        for cid, items in by_company.items():
            signed = sum(
                (
                    (h.notional or Decimal(0)) * (-1 if h.swap_direction == "short" else 1)
                    for h, _ in items
                ),
                Decimal(0),
            )
            edge_id = conn.execute(
                text(
                    """
                    INSERT INTO edge
                        (src_id, dst_id, type, weight, valid_from, confidence, known_at)
                    VALUES (:s, :d, 'SYNTHETIC', :w, :vf, :c, :k)
                    ON CONFLICT (src_id, dst_id, type, valid_from, known_at)
                    DO UPDATE SET weight = EXCLUDED.weight, confidence = EXCLUDED.confidence
                    RETURNING id
                    """
                ),
                {
                    "s": fund_id,
                    "d": cid,
                    "w": signed / rpt.net_assets,
                    "vf": valid_from,
                    "c": min(conf for _, conf in items),
                    "k": rpt.known_at,
                },
            ).scalar_one()
            conn.execute(
                text(
                    """
                    INSERT INTO edge_evidence (edge_id, doc_id, section, span_text, url)
                    VALUES (:e, :doc,
                            'formData/invstOrSecs/invstOrSec/derivativeInfo/swapDeriv',
                            :span, :url)
                    ON CONFLICT (edge_id, doc_id, section, span_text) DO NOTHING
                    """
                ),
                [
                    {
                        "e": edge_id,
                        "doc": stored.doc_id,
                        "span": h.span_text,
                        "url": stored.raw.url or "",
                    }
                    for h, _ in items
                ],
            )

    def _write_edges(
        self,
        conn: Connection,
        stored: StoredPayload,
        rpt: NportReport,
        fund_id: int,
        resolved: list[tuple[NportHolding, int | None, str | None, Decimal | None]],
    ) -> None:
        valid_from = datetime.combine(rpt.report_date, time(0, 0), tzinfo=UTC)
        # Re-parsing the same report version replaces its edges (alias fixes can move a line to a
        # different company); evidence rows go with them.
        conn.execute(
            text(
                "DELETE FROM edge WHERE src_id = :f AND type IN ('CONTAINS', 'SYNTHETIC') "
                "AND valid_from = :vf AND known_at = :k"
            ),
            {"f": fund_id, "vf": valid_from, "k": rpt.known_at},
        )
        by_company: dict[int, list[tuple[NportHolding, Decimal]]] = {}
        for h, cid, _, conf in resolved:
            if (
                cid is not None
                and conf is not None
                and h.asset_cat in EQUITY_CATS
                and h.payoff_profile == "Long"
                and h.pct_val is not None
            ):
                by_company.setdefault(cid, []).append((h, conf))
        for cid, items in by_company.items():
            weight = sum((h.pct_val or Decimal(0) for h, _ in items), Decimal(0)) / 100
            confidence = min(conf for _, conf in items)
            edge_id = conn.execute(
                text(
                    """
                    INSERT INTO edge
                        (src_id, dst_id, type, weight, valid_from, confidence, known_at)
                    VALUES (:s, :d, 'CONTAINS', :w, :vf, :c, :k)
                    ON CONFLICT (src_id, dst_id, type, valid_from, known_at)
                    DO UPDATE SET weight = EXCLUDED.weight, confidence = EXCLUDED.confidence
                    RETURNING id
                    """
                ),
                {
                    "s": fund_id,
                    "d": cid,
                    "w": weight,
                    "vf": valid_from,
                    "c": confidence,
                    "k": rpt.known_at,
                },
            ).scalar_one()
            conn.execute(
                text(
                    """
                    INSERT INTO edge_evidence (edge_id, doc_id, section, span_text, url)
                    VALUES (:e, :doc, 'formData/invstOrSecs/invstOrSec', :span, :url)
                    ON CONFLICT (edge_id, doc_id, section, span_text) DO NOTHING
                    """
                ),
                [
                    {
                        "e": edge_id,
                        "doc": stored.doc_id,
                        "span": h.span_text,
                        "url": stored.raw.url or "",
                    }
                    for h, _ in items
                ],
            )
        self._write_synthetic_edges(conn, stored, rpt, fund_id, resolved, valid_from)
        # A report's edges end when the fund's next report begins (also right when backfilling).
        conn.execute(
            text(
                """
                WITH reports AS (
                    SELECT valid_from, lead(valid_from) OVER (ORDER BY valid_from) AS nxt
                    FROM (SELECT DISTINCT valid_from FROM edge
                          WHERE src_id = :f AND type = 'CONTAINS') d)
                UPDATE edge e SET valid_to = reports.nxt
                FROM reports
                WHERE e.src_id = :f AND e.type = 'CONTAINS' AND e.valid_from = reports.valid_from
                  AND reports.nxt IS NOT NULL AND e.valid_to IS DISTINCT FROM reports.nxt
                """
            ),
            {"f": fund_id},
        )

import csv

from stockiq.entities.eval import FIELDS, Scored, gold_path, report, summarise, unreviewed_scored


def _row(name: str, expected: str, reviewed: str = "") -> dict[str, str]:
    return {
        "cusip": "1", "isin": "", "lei": "", "name": name, "expected_cik": expected,
        "expected_name": "", "label_source": "t", "note": "", "reviewed": reviewed,
    }  # fmt: skip


def test_precision_counts_only_links_and_recall_counts_all_labelled_rows() -> None:
    scored = [
        Scored(_row("a", "1"), "1", "A", 0.95, "exact_name"),  # correct
        Scored(_row("b", "2"), "9", "B", 0.80, "fuzzy_name"),  # linked, wrong
        Scored(_row("c", "3"), None, None, 0.0, "none"),  # not linked
        Scored(_row("d", ""), "7", "D", 0.95, "exact_name"),  # no label: not scored at all
    ]
    s = summarise(scored)
    assert (s["labelled"], s["linked"], s["correct"]) == (3, 2, 1)
    assert s["precision"] == 0.5 and abs(s["recall"] - 1 / 3) < 1e-9


def test_an_empty_sample_scores_zero_not_a_crash() -> None:
    s = summarise([])
    assert (s["precision"], s["recall"], s["labelled"]) == (0.0, 0.0, 0)


def test_report_lists_wrong_links_by_method_and_flags_unreviewed_labels() -> None:
    scored = [
        Scored(_row("Hartford Financial", "5", "yes"), "9", "PNC", 0.66, "fuzzy_name"),
        Scored(_row("Apple", "1", "yes"), "1", "Apple", 0.95, "exact_name"),
    ]
    text = report(scored)
    assert "Wrong links:" in text and "'Hartford Financial' -> 'PNC'" in text
    assert "fuzzy_name" in text and "0 of 2 labels have not been reviewed" in text


def test_the_committed_gold_file_has_the_agreed_columns() -> None:
    path = gold_path("etf_holdings")
    assert path.exists(), "run: python -m stockiq.entities.eval build-gold --source etf_holdings"
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == FIELDS
        rows = list(reader)
    assert len(rows) >= 100
    assert all(r["cusip"] for r in rows)
    assert len({r["cusip"] for r in rows}) == len(rows)  # no duplicate mentions


def test_the_gate_counts_only_scored_rows_that_lack_a_review() -> None:
    scored = [
        Scored(_row("a", "1", "yes"), "1", "A", 0.95, "exact_name"),  # reviewed
        Scored(_row("b", "2", ""), "2", "B", 0.95, "exact_name"),  # scored, not reviewed
        Scored(
            _row("c", "", ""), None, None, 0.0, "none"
        ),  # no label: never scored, so not counted
    ]
    assert unreviewed_scored(scored) == 1

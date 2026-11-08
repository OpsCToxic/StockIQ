from stockiq.graph.exposure import BUCKET_LABELS, bucket_for


def test_matched_long_equity_is_company_exposure_not_part_of_the_remainder() -> None:
    assert bucket_for("EC", "Long", matched=True) is None
    assert bucket_for("EP", "Long", matched=True) is None


def test_unmatched_long_equity_is_the_real_gap() -> None:
    assert bucket_for("EC", "Long", matched=False) == "unmatched_equity"


def test_short_equity_is_not_counted_as_a_matching_gap() -> None:
    assert bucket_for("EC", "Short", matched=True) == "other"


def test_money_market_and_repo_are_cash_like_collateral() -> None:
    assert bucket_for("STIV", "Long", matched=False) == "cash"
    assert bucket_for("RA", "Long", matched=False) == "cash"


def test_derivative_categories_are_derivatives_but_debt_is_not() -> None:
    for cat in ("DE", "DIR", "DFE", "DO", "DCO"):
        assert bucket_for(cat, "N/A", matched=True) == "derivatives"  # even a matched swap
    assert bucket_for("DBT", "Long", matched=False) == "debt"  # starts with D, but it is debt
    assert bucket_for("ABS-MBS", "Long", matched=False) == "debt"
    assert bucket_for("LON", "Long", matched=False) == "debt"


def test_unknown_or_missing_categories_go_to_other_and_every_bucket_has_a_label() -> None:
    assert bucket_for(None, None, matched=False) == "other"
    assert bucket_for("ZZ", "Long", matched=False) == "other"
    for bucket in ("cash", "derivatives", "debt", "unmatched_equity", "other", "unknown"):
        assert bucket in BUCKET_LABELS

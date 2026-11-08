from stockiq.entities.names import GENERIC, distinctive_tokens, normalize_name


def test_dotted_initials_collapse() -> None:
    assert normalize_name("NXP Semiconductors N.V.") == normalize_name("NXP Semiconductors NV")
    assert (
        normalize_name("W.W. GRAINGER, INC.") == normalize_name("WW Grainger Inc") == "ww grainger"
    )


def test_cos_and_companies_are_legal_forms() -> None:
    assert normalize_name("Marsh & McLennan Cos Inc") == normalize_name(
        "MARSH & MCLENNAN COMPANIES, INC."
    )
    assert normalize_name("Estee Lauder Cos Inc/The") == normalize_name(
        "ESTEE LAUDER COMPANIES INC"
    )


def test_a_name_made_only_of_legal_words_is_kept_not_emptied() -> None:
    assert normalize_name("Companies Inc") == "companies"
    assert normalize_name("The Co") == "co"


def test_distinctive_tokens_drop_generic_words() -> None:
    assert distinctive_tokens("hartford financial services group") == {"hartford"}
    assert distinctive_tokens("pnc financial services group") == {"pnc"}
    assert distinctive_tokens("a o smith") == {"a", "o", "smith"}
    assert "group" in GENERIC and "tesla" not in GENERIC


def test_backslash_state_tags_are_stripped_too() -> None:
    assert normalize_name("US BANCORP \\DE\\") == normalize_name("US Bancorp") == "us bancorp"

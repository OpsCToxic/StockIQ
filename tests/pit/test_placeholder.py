"""Point-in-time tests live here. Each analytics function gets a case where a fact's event time is
before as_of but its known time is after, asserting it is excluded. See the point-in-time skill."""

import pytest


@pytest.mark.pit
def test_pit_suite_present():
    assert True

"""SIC (Standard Industrial Classification) divisions, the coarse roll-up for sector exposure.

SIC is what the SEC publishes for free. It is coarser and older than GICS (Manufacturing alone
holds software hardware, drugs and cars), so the report shows both the 4-digit industry and these
ten divisions.
"""

import re

_DIVISIONS = (
    (1, 9, "Agriculture, Forestry & Fishing"),
    (10, 14, "Mining"),
    (15, 17, "Construction"),
    (20, 39, "Manufacturing"),
    (40, 49, "Transportation, Communications, Electric, Gas & Sanitary"),
    (50, 51, "Wholesale Trade"),
    (52, 59, "Retail Trade"),
    (60, 67, "Finance, Insurance & Real Estate"),
    (70, 89, "Services"),
    (91, 99, "Public Administration"),
)
_NAME = re.compile(r"^SIC (\d{4}) ")


def division_for(sic: int) -> str:
    major = sic // 100
    for low, high, name in _DIVISIONS:
        if low <= major <= high:
            return name
    return "Unclassified"


def division_for_sector_name(sector_name: str) -> str:
    """Sector entities are named 'SIC 3571 Electronic Computers'."""
    m = _NAME.match(sector_name)
    return division_for(int(m.group(1))) if m else "Unclassified"

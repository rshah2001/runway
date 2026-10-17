"""The judged demo, pinned on the real forecast engine and the seeded personas, for every day it could
run: Maya is $135 short; Sam authorized $150 but can safely give $90; Jordan authorized $300 but his
mortgage leaves no safe room; Emma gives $45. Runway coordinates Sam $90 + Emma $45."""

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from app import prefs
from app.cashflow import projection_for
from app.guardian import DEFAULT_EXPOSURE
from app.safety_net import Helper, decide
from seed.personas import PERSONAS, SAFETY_LIMITS

AGES = {p.slug: p.age for p in PERSONAS}


def project(slug: str, today: date):
    p = projection_for(slug, first_name=slug.title(), age=AGES[slug], today=today)
    return replace(p, floor=D(str(prefs.default_floor(slug))))


@pytest.mark.parametrize("offset", range(5))
def test_maya_is_covered_by_sam_90_and_emma_45_and_jordan_is_protected(offset: int) -> None:
    today = date(2026, 10, 18) + timedelta(days=offset)
    helpers = [
        Helper(project(lender, today), D(str(limit)), D(0), True, False, DEFAULT_EXPOSURE)
        for lender, borrower, limit in SAFETY_LIMITS
        if borrower == "maya"
    ]
    d = decide(project("maya", today), helpers, today)
    assert d.action == "auto_bridge", d.reason
    assert d.amount == D(135)
    assert dict(d.allocations) == {"sam": D(90), "emma": D(45)}  # Jordan gives nothing


def test_jordan_is_protected_and_told_without_naming_anyone() -> None:
    today = date(2026, 10, 18)
    helpers = [
        Helper(project(lender, today), D(str(limit)), D(0), True, False, DEFAULT_EXPOSURE)
        for lender, borrower, limit in SAFETY_LIMITS
        if borrower == "maya"
    ]
    d = decide(project("maya", today), helpers, today)
    assert [(slug, why) for slug, _, why in d.held] == [("jordan", "cushion")]

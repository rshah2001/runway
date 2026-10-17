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


def test_jordan_is_protected_and_the_reason_is_his_own_cushion() -> None:
    today = date(2026, 10, 18)
    helpers = [
        Helper(project(lender, today), D(str(limit)), D(0), True, False, DEFAULT_EXPOSURE)
        for lender, borrower, limit in SAFETY_LIMITS
        if borrower == "maya"
    ]
    d = decide(project("maya", today), helpers, today)
    assert [(slug, why) for slug, _, why in d.held] == [("jordan", "cushion")]


@pytest.mark.parametrize("offset", range(5))
def test_maya_and_alex_short_the_same_week_are_split_fairly(offset: int) -> None:
    """Demo 5: Sam's $90 of safe room is shared by Maya and his roommate Alex. Fewest options first:
    Maya (no alternative to Sam) is covered in full; Alex gets Emma's $50 and $35 stays uncovered."""
    from app.safety_net import network_pass
    from seed.personas import DEMO_PAUSED, DEMO_WAITING_FOR_RECIPIENT

    today = date(2026, 10, 18) + timedelta(days=offset)

    def decision(borrower: str):
        helpers = [
            Helper(project(s, today), D(str(lim)), D(0), True, False, DEFAULT_EXPOSURE)
            for s, r, lim in SAFETY_LIMITS
            if r == borrower and (s, r) not in DEMO_PAUSED and (s, r) not in DEMO_WAITING_FOR_RECIPIENT
        ]
        return decide(project(borrower, today), helpers, today)

    alone = decision("alex")
    assert alone.amount == D(85)
    out = {d.borrower: d for d in network_pass([decision("alex"), decision("maya")])}
    assert dict(out["maya"].allocations) == {"sam": D(90), "emma": D(45)}
    assert dict(out["alex"].allocations) == {"emma": D(50)} and "couldn't be covered" in out["alex"].reason
    assert "short" not in out["alex"].reason.split(". ", 1)[1] and "others" not in out["alex"].reason.lower()

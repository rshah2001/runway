"""The seed plan is pure, so its guarantees can be tested without touching Nessie."""

from datetime import date, timedelta

import pytest

from seed.personas import MERCHANTS, PERSONAS
from seed.plan import HISTORY_DAYS, build_plan

TODAY = date(2026, 10, 16)  # a Friday — the edge case for "next payday is never today"
BY_SLUG = {p.slug: p for p in PERSONAS}


@pytest.mark.parametrize("spec", PERSONAS, ids=lambda p: p.slug)
def test_history_is_strictly_before_today_and_within_window(spec) -> None:
    for op in build_plan(spec, TODAY):
        if op.bill_status == "recurring":
            assert op.on >= TODAY
        else:
            assert TODAY - timedelta(days=HISTORY_DAYS) <= op.on < TODAY


@pytest.mark.parametrize("spec", PERSONAS, ids=lambda p: p.slug)
def test_plan_is_deterministic(spec) -> None:
    assert build_plan(spec, TODAY) == build_plan(spec, TODAY)


def test_every_merchant_used_is_in_the_catalog() -> None:
    used = {op.merchant for spec in PERSONAS for op in build_plan(spec, TODAY) if op.merchant}
    assert used <= set(MERCHANTS)


def test_one_upcoming_bill_per_scheduled_bill() -> None:
    for spec in PERSONAS:
        upcoming = [op for op in build_plan(spec, TODAY) if op.bill_status == "recurring"]
        assert sorted(op.description for op in upcoming) == sorted(b.nickname for b in spec.bills)


def test_maya_is_paid_biweekly_on_fridays_but_not_today() -> None:
    paydays = [op.on for op in build_plan(BY_SLUG["maya"], TODAY) if op.kind == "deposit"]
    assert paydays and all(d.weekday() == 4 for d in paydays)
    assert all((b - a).days == 14 for a, b in zip(paydays, paydays[1:], strict=False))
    assert TODAY not in paydays and paydays[-1] == TODAY - timedelta(days=7)  # next one is Oct 23


def test_jordan_has_subscription_creep() -> None:
    subs = {
        op.merchant
        for op in build_plan(BY_SLUG["jordan"], TODAY)
        if MERCHANTS.get(op.merchant or "", ("",))[0] == "Subscriptions"
    }
    assert len(subs) >= 8


def test_personas_are_20_40_60_and_emma_32() -> None:
    assert [(p.slug, p.age) for p in PERSONAS] == [("maya", 20), ("jordan", 40), ("sam", 60), ("emma", 32)]


@pytest.mark.parametrize("spec", PERSONAS, ids=lambda p: p.slug)
def test_p2p_history_only_involves_the_personas_own_contacts(spec) -> None:
    keys = {c.key for c in spec.contacts}
    p2p = [op for op in build_plan(spec, TODAY) if op.kind == "p2p"]
    assert p2p, "every persona has some peer-to-peer history"
    assert all(op.contact in keys and op.direction in ("in", "out") and op.amount > 0 for op in p2p)
    assert all(r.contact in keys and r.amount > 0 for r in spec.requests)


def test_adding_p2p_does_not_reshuffle_purchases() -> None:
    """P2P uses its own random stream, so purchase history (and the backtest) stays stable."""
    from dataclasses import replace

    maya = BY_SLUG["maya"]
    without = [op for op in build_plan(replace(maya, p2p=[]), TODAY) if op.kind == "purchase"]
    with_p2p = [op for op in build_plan(maya, TODAY) if op.kind == "purchase"]
    assert without == with_p2p

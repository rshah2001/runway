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

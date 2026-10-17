"""Forecast engine unit tests. Every case pins `start` so results never depend on today's date."""

from datetime import date, timedelta

import pytest

from app.forecast import engine
from app.forecast.schedule import MAYA, CardStatement, MonthlyCharge, Paycheck, Schedule
from app.schemas import ForecastEvent

DEMO_DAY = date(2026, 10, 16)  # a Friday, a week before payday, with rent coming on Nov 1


def _labels_on(forecast, d: date) -> set[str]:
    return {e.label for e in forecast.events if e.date == d}


def test_demo_story_dips_below_floor_and_100_dollars_fixes_it() -> None:
    f = engine.forecast(start=DEMO_DAY)
    assert f.low.date == date(2026, 11, 5)
    assert f.low.balance == pytest.approx(251.61)
    assert f.low.balance < f.safe_floor < f.low.balance + 100


def test_points_cover_today_through_horizon() -> None:
    f = engine.forecast(days=30, start=DEMO_DAY)
    assert [p.date for p in f.points] == [DEMO_DAY + timedelta(days=i) for i in range(31)]
    assert all(DEMO_DAY <= e.date <= DEMO_DAY + timedelta(days=30) for e in f.events)


def test_balance_is_start_plus_running_sum_of_events() -> None:
    f = engine.forecast(days=60, start=DEMO_DAY)
    for p in f.points:
        expected = MAYA.start_balance + sum(e.amount for e in f.events if e.date <= p.date)
        assert p.balance == pytest.approx(expected)


def test_paycheck_is_never_today_and_repeats_every_14_days() -> None:
    f = engine.forecast(days=60, start=DEMO_DAY)  # DEMO_DAY is itself a Friday
    paydays = [e.date for e in f.events if e.kind == "paycheck"]
    assert paydays[0] == DEMO_DAY + timedelta(days=7)
    assert all((b - a).days == 14 for a, b in zip(paydays, paydays[1:], strict=False))


def test_bill_on_the_31st_clamps_to_month_end() -> None:
    schedule = Schedule(
        start_balance=1000, safe_floor=0, paycheck=Paycheck(0, 14, "Pay"), monthly=[MonthlyCharge(31, 10, "Gym")]
    )
    f = engine.forecast(days=60, start=date(2027, 2, 1), schedule=schedule)
    gym = [e.date for e in f.events if e.label == "Gym"]
    assert gym == [date(2027, 2, 28), date(2027, 3, 31)]


def test_card_statement_is_paid_once_on_next_pay_day() -> None:
    schedule = Schedule(
        start_balance=500, safe_floor=0, paycheck=Paycheck(0, 14, "Pay"), cards=[CardStatement("Card", 200, 22)]
    )
    f = engine.forecast(days=90, start=date(2026, 10, 23), schedule=schedule)
    payoffs = [e for e in f.events if e.kind == "card_payment"]
    assert [(e.date, e.amount) for e in payoffs] == [(date(2026, 11, 22), -200)]


def test_installments_start_next_month() -> None:
    f = engine.forecast(days=60, start=DEMO_DAY)
    laptop = [e.date for e in f.events if e.label.startswith("Laptop")]
    assert laptop == [date(2026, 11, 28)]


def test_simulated_purchase_lowers_every_later_day_by_its_amount() -> None:
    base = engine.forecast(start=DEMO_DAY)
    after = engine.simulate_purchase(180, DEMO_DAY + timedelta(days=7), "Concert", start=DEMO_DAY)
    for b, a in zip(base.points, after.points, strict=False):
        assert a.balance == pytest.approx(b.balance - (180 if b.date >= DEMO_DAY + timedelta(days=7) else 0))


def test_past_dated_purchase_counts_now_instead_of_breaking_the_forecast() -> None:
    base = engine.forecast(start=DEMO_DAY)
    after = engine.simulate_purchase(50, DEMO_DAY - timedelta(days=3), "Purchase", start=DEMO_DAY)
    assert after.points[0].balance == pytest.approx(base.points[0].balance - 50)
    assert after.low.balance == pytest.approx(base.low.balance - 50)


def test_far_off_purchase_extends_the_horizon_instead_of_being_dropped() -> None:
    on = DEMO_DAY + timedelta(days=90)
    after = engine.simulate_purchase(500, on, "Trip", start=DEMO_DAY)
    assert after.points[-1].date >= on
    assert any(e.label == "Trip" for e in after.events)


def test_extra_events_outside_the_window_are_ignored() -> None:
    stale = ForecastEvent(date=DEMO_DAY - timedelta(days=1), amount=-999, label="Old", kind="other")
    assert engine.forecast(extra=[stale], start=DEMO_DAY) == engine.forecast(start=DEMO_DAY)


def test_recurring_next_dates_are_on_or_after_start() -> None:
    subs = engine.recurring(start=DEMO_DAY)
    assert {s.merchant for s in subs} == {"Music streaming", "Video streaming", "Cloud storage"}
    assert all(s.next_date >= DEMO_DAY and s.amount > 0 for s in subs)

"""Forecast engine tests: hand-built schedules for exact math, seeded personas for the demo stories.

Every test pins `start`, and tests run on the seeded demo data (see conftest.py), so nothing depends
on today's date or a live database.
"""

from datetime import date, timedelta

import pytest

from app.forecast import engine, schedule, sources
from app.forecast.schedule import MonthlyCharge, RegularFlow, Schedule
from app.forecast.spend_model import SpendProfile
from app.schemas import ForecastEvent

TODAY = date(2026, 10, 16)  # a Friday
FLAT_10 = SpendProfile((10.0,) * 7)


def _schedule(**kwargs) -> Schedule:
    return Schedule(start_balance=kwargs.pop("start_balance", 1000.0), **kwargs)


# ---------- engine math on hand-built schedules ----------


def test_points_cover_today_through_horizon() -> None:
    f = engine.forecast(days=30, start=TODAY, schedule=_schedule())
    assert [p.date for p in f.points] == [TODAY + timedelta(days=i) for i in range(31)]


def test_balance_is_start_plus_running_sum_of_events() -> None:
    s = _schedule(monthly=[MonthlyCharge(1, 650, "Rent")], spend=FLAT_10)
    f = engine.forecast(days=60, start=TODAY, schedule=s)
    for p in f.points:
        expected = 1000 + sum(e.amount for e in f.events if e.date <= p.date)
        assert p.balance == pytest.approx(expected)


def test_bill_on_the_31st_clamps_to_month_end() -> None:
    s = _schedule(monthly=[MonthlyCharge(31, 10, "Gym")])
    f = engine.forecast(days=60, start=date(2027, 2, 1), schedule=s)
    assert [e.date for e in f.events if e.label == "Gym"] == [date(2027, 2, 28), date(2027, 3, 31)]


def test_regular_flows_repeat_on_their_cadence() -> None:
    pay = RegularFlow("Paycheck", 780, 14, TODAY + timedelta(days=7), "paycheck")
    split = RegularFlow("Rent split", -300, 30, date(2026, 11, 3), "transfer")
    f = engine.forecast(days=45, start=TODAY, schedule=_schedule(regular=[pay, split]))
    assert [e.date for e in f.events if e.label == "Paycheck"] == [
        date(2026, 10, 23),
        date(2026, 11, 6),
        date(2026, 11, 20),
    ]
    assert [(e.date, e.amount) for e in f.events if e.label == "Rent split"] == [(date(2026, 11, 3), -300)]


def test_everyday_spending_is_booked_weekly_and_adds_up() -> None:
    f = engine.forecast(days=20, start=TODAY, schedule=_schedule(spend=FLAT_10))
    spend = [e for e in f.events if e.kind == "spending"]
    assert [e.date for e in spend] == [TODAY, TODAY + timedelta(days=7), TODAY + timedelta(days=14)]
    assert sum(e.amount for e in spend) == pytest.approx(-10 * 21)  # every day of the window, no more


def test_simulated_purchase_lowers_every_later_day_by_its_amount() -> None:
    s = _schedule(spend=FLAT_10)
    base = engine.forecast(start=TODAY, schedule=s)
    after = engine.simulate_purchase(180, TODAY + timedelta(days=7), "Concert", start=TODAY, schedule=s)
    for b, a in zip(base.points, after.points, strict=False):
        assert a.balance == pytest.approx(b.balance - (180 if b.date >= TODAY + timedelta(days=7) else 0))


def test_past_dated_purchase_counts_now_instead_of_breaking_the_forecast() -> None:
    s = _schedule()
    after = engine.simulate_purchase(50, TODAY - timedelta(days=3), "Purchase", start=TODAY, schedule=s)
    assert after.points[0].balance == pytest.approx(950)


def test_far_off_purchase_extends_the_horizon_instead_of_being_dropped() -> None:
    on = TODAY + timedelta(days=90)
    after = engine.simulate_purchase(500, on, "Trip", start=TODAY, schedule=_schedule())
    assert after.points[-1].date >= on and any(e.label == "Trip" for e in after.events)


def test_extra_events_outside_the_window_are_ignored() -> None:
    s = _schedule(spend=FLAT_10)
    stale = ForecastEvent(date=TODAY - timedelta(days=1), amount=-999, label="Old", kind="other")
    assert engine.forecast(extra=[stale], start=TODAY, schedule=s) == engine.forecast(start=TODAY, schedule=s)


@pytest.mark.parametrize(
    ("low", "expected"),
    [(299.99, "overdraft_risk"), (300, "tight"), (449.99, "tight"), (450, "healthy"), (-50, "overdraft_risk")],
)
def test_status_thresholds(low: float, expected: str) -> None:
    assert engine.status(low, 300) == expected


# ---------- schedules learned from the seeded personas ----------


@pytest.mark.parametrize(("persona", "paycheck"), [("maya", 780.0), ("jordan", 2900.0), ("sam", 3100.0)])
def test_paycheck_is_detected_from_history(persona: str, paycheck: float) -> None:
    s = engine.schedule_for(persona, TODAY)
    [pay] = [f for f in s.regular if f.kind == "paycheck"]
    assert pay.amount == paycheck and pay.interval_days == 14
    assert pay.next_date == date(2026, 10, 23)  # the seed's next payday: the coming Friday, never today


def test_bills_come_from_the_bills_table_and_card_payment_is_tagged() -> None:
    s = engine.schedule_for("maya", TODAY)
    assert {c.label for c in s.monthly} >= {"Rent", "Credit card payment"}
    assert next(c for c in s.monthly if c.label == "Credit card payment").kind == "card_payment"


def test_regular_transfers_out_are_scheduled_not_guessed() -> None:
    s = engine.schedule_for("jordan", TODAY)
    assert any(f.label == "Kids soccer fees" and f.amount == -60 for f in s.regular)


def test_card_purchases_are_not_counted_twice() -> None:
    data = sources.load("maya", TODAY)
    everyday = schedule.everyday_outflows(data.history, [])
    card_total = sum(-t.amount for t in data.history if t.account == "Credit Card" and t.kind == "purchase")
    assert card_total > 0 and sum(a for _, a in everyday) < sum(-t.amount for t in data.history if t.amount < 0)
    assert all(t.account == "Checking" for t in data.history if (t.date, -t.amount) in set(everyday))


def test_demo_stories_hold() -> None:
    maya, jordan, sam = (engine.forecast(start=TODAY, persona=p) for p in ("maya", "jordan", "sam"))
    assert engine.status(maya.low.balance, maya.safe_floor) == "overdraft_risk"  # rent lands before payday
    assert engine.status(sam.low.balance, sam.safe_floor) == "healthy"
    assert jordan.low.balance > jordan.safe_floor


def test_unknown_persona_is_an_error_not_maya() -> None:
    with pytest.raises(sources.UnknownPersona):
        engine.forecast(start=TODAY, persona="mallory")


def test_demo_history_uses_the_database_sign_convention() -> None:
    data = sources.load("maya", TODAY)
    assert all(t.amount > 0 for t in data.history if t.kind == "deposit")
    assert all(t.amount < 0 for t in data.history if t.kind in ("purchase", "bill", "transfer"))
    assert all(t.date < TODAY for t in data.history)

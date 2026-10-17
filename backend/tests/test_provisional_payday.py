"""Provisional payday: two matching paychecks put income in a new user's forecast, clearly marked."""

from datetime import date, timedelta

import pytest

from app.forecast import engine, schedule, sources
from app.forecast.recurring import provisional
from app.forecast.sources import Txn

TODAY = date(2026, 10, 16)  # a Friday


def _deposits(label: str, dates: list[date], amount: float | list[float]) -> list[Txn]:
    amounts = amount if isinstance(amount, list) else [amount] * len(dates)
    return [Txn(d, "deposit", a, label, "Income", "Checking") for d, a in zip(dates, amounts, strict=True)]


def _person(history: list[Txn]) -> sources.PersonaData:
    spend = [Txn(TODAY - timedelta(days=i), "purchase", -12.0, "Grocer", "Food", "Checking") for i in range(30, 0, -1)]
    return sources.PersonaData("new", 600.0, 300.0, bills=[], history=sorted(history + spend, key=lambda t: t.date))


def _income(t: Txn) -> bool:
    return t.kind == "deposit" and t.amount > 0


# ---------- the two-deposit rule ----------


def test_two_paychecks_two_weeks_apart_predict_the_next() -> None:
    [pay] = provisional(_deposits("Acme payroll", [date(2026, 9, 25), date(2026, 10, 9)], 950.0), TODAY, _income)
    assert (pay.interval_days, pay.next_date, pay.amount) == (14, date(2026, 10, 23), 950.0)


def test_two_monthly_paychecks_on_the_same_day_predict_the_next() -> None:
    [pay] = provisional(_deposits("Pension", [date(2026, 8, 28), date(2026, 9, 28)], 2100.0), TODAY, _income)
    assert pay.interval_days == 30 and pay.next_date == date(2026, 10, 28)


@pytest.mark.parametrize(
    ("why", "dates", "amounts"),
    [
        ("only one paycheck", [date(2026, 10, 9)], [950.0]),
        ("amounts differ by more than 5%", [date(2026, 9, 25), date(2026, 10, 9)], [950.0, 700.0]),
        ("a gap that fits no pay rhythm", [date(2026, 9, 19), date(2026, 10, 9)], [950.0, 950.0]),
        ("the next one is long overdue", [date(2026, 8, 7), date(2026, 8, 21)], [950.0, 950.0]),
    ],
)
def test_it_refuses_to_guess(why: str, dates: list[date], amounts: list[float]) -> None:
    assert provisional(_deposits("Acme payroll", dates, amounts), TODAY, _income) == [], why


def test_three_paychecks_are_confirmed_not_provisional() -> None:
    dates = [date(2026, 9, 11), date(2026, 9, 25), date(2026, 10, 9)]
    assert provisional(_deposits("Acme payroll", dates, 950.0), TODAY, _income) == []
    flows = schedule.regular_flows(_deposits("Acme payroll", dates, 950.0), TODAY)
    assert [(f.kind, f.provisional) for f in flows] == [("paycheck", False)]


# ---------- in the forecast and in readiness ----------


def test_a_provisional_paycheck_is_in_the_forecast() -> None:
    data = _person(_deposits("Acme payroll", [date(2026, 9, 25), date(2026, 10, 9)], 950.0))
    f = engine.forecast(days=30, start=TODAY, schedule=schedule.build(data, TODAY))
    assert [e.date for e in f.events if e.kind == "paycheck"] == [date(2026, 10, 23), date(2026, 11, 6)]


def test_readiness_says_it_is_only_counting_on_it() -> None:
    data = _person(_deposits("Acme payroll", [date(2026, 9, 25), date(2026, 10, 9)], 950.0))
    r = schedule.build(data, TODAY).readiness
    assert r is not None and not r.paycheck_found  # counted on, not confirmed
    assert r.status == "learning"  # never "confident" on a payday seen twice
    assert any("I've seen 2 paychecks of $950.00 14 days apart" in reason for reason in r.reasons)


def test_a_small_confirmed_allowance_does_not_outrank_a_bigger_provisional_paycheck() -> None:
    allowance = _deposits("Mom", [date(2026, 9, 18), date(2026, 9, 25), date(2026, 10, 2), date(2026, 10, 9)], 50.0)
    pay = _deposits("Acme payroll", [date(2026, 9, 25), date(2026, 10, 9)], 950.0)
    flows = {f.label: f for f in schedule.regular_flows(allowance + pay, TODAY)}
    assert flows["Acme payroll"].kind == "paycheck" and flows["Acme payroll"].provisional
    assert flows["Mom"].kind == "transfer"


def test_seeded_personas_keep_their_confirmed_paychecks() -> None:
    for persona in ("maya", "jordan", "sam"):
        r = engine.readiness(persona, TODAY)
        assert r.paycheck_found and r.status == "confident"
        assert not any("I'll be sure after" in reason for reason in r.reasons)

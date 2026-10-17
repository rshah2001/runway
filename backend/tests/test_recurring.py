"""Recurring-transaction detector tests on hand-built histories, plus the seeded demo history."""

from datetime import date, timedelta

from app.forecast.history import Transaction, demo_history
from app.forecast.recurring import detect_recurring

TODAY = date(2026, 10, 16)


def _charges(merchant: str, dates: list[date], amounts: list[float] | float) -> list[Transaction]:
    amounts = amounts if isinstance(amounts, list) else [amounts] * len(dates)
    return [Transaction(d, merchant, a, "Other", "purchase") for d, a in zip(dates, amounts, strict=True)]


def _monthly(day: int, n: int = 4) -> list[date]:
    return [date(2026, 10 - i, day) for i in range(n, 0, -1)]  # Jun..Sep


def test_finds_a_monthly_subscription_and_its_next_charge() -> None:
    [sub] = detect_recurring(_charges("StreamCo", _monthly(14), 15.49), TODAY)
    assert (sub.merchant, sub.amount, sub.next_date) == ("StreamCo", 15.49, date(2026, 10, 14) + timedelta(days=31))


def test_finds_a_weekly_charge() -> None:
    dates = [TODAY - timedelta(days=7 * i) for i in range(5, 0, -1)]
    [gym] = detect_recurring(_charges("Gym", dates, 12.00), TODAY)
    assert gym.interval_days == 7 and gym.next_date == TODAY


def test_frequent_but_varying_purchases_are_not_recurring() -> None:
    dates = [TODAY - timedelta(days=7 * i) for i in range(6, 0, -1)]
    assert detect_recurring(_charges("Coffee", dates, [5.10, 8.75, 6.20, 7.95, 5.40, 8.10]), TODAY) == []


def test_same_amount_at_irregular_times_is_not_recurring() -> None:
    dates = [TODAY - timedelta(days=d) for d in (80, 61, 50, 19, 3)]
    assert detect_recurring(_charges("Parking", dates, 4.00), TODAY) == []


def test_two_charges_are_not_enough_evidence() -> None:
    assert detect_recurring(_charges("StreamCo", _monthly(14, n=2), 15.49), TODAY) == []


def test_cancelled_subscription_is_dropped() -> None:
    dates = [date(2026, m, 3) for m in (4, 5, 6, 7)]  # last charge Jul 3, nothing since
    assert detect_recurring(_charges("OldApp", dates, 9.99), TODAY) == []


def test_one_late_charge_is_tolerated() -> None:
    dates = [date(2026, 6, 8), date(2026, 7, 8), date(2026, 8, 15), date(2026, 9, 8), date(2026, 10, 8)]
    [sub] = detect_recurring(_charges("Music", dates, 11.99), TODAY)
    assert sub.next_date == date(2026, 11, 8)  # the late Aug 15 charge doesn't move the billing day


def test_month_end_billing_returns_to_the_31st_after_february() -> None:
    dates = [date(2026, 12, 31), date(2027, 1, 31), date(2027, 2, 28)]
    [sub] = detect_recurring(_charges("Cloud", dates, 2.99), date(2027, 3, 1))
    assert sub.next_date == date(2027, 3, 31)


def test_bills_and_deposits_are_ignored() -> None:
    history = [Transaction(d, "Rent", 650, "Bill", "bill") for d in _monthly(1)]
    history += [Transaction(d, "Payroll", -780, "Income", "deposit") for d in _monthly(9)]
    assert detect_recurring(history, TODAY) == []


def test_demo_history_yields_exactly_the_personas_subscriptions() -> None:
    found = detect_recurring(demo_history(TODAY), TODAY)
    assert {(r.merchant, r.amount) for r in found} == {
        ("Music streaming", 11.99),
        ("Video streaming", 15.49),
        ("Cloud storage", 9.99),
    }
    assert [r.next_date for r in found] == sorted(r.next_date for r in found)

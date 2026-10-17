from datetime import date, timedelta
from decimal import Decimal as D

from app.cashflow import build_projection, detect_paydays

TODAY = date(2026, 10, 16)  # Friday


def test_detects_a_biweekly_paycheck_and_ignores_small_deposits() -> None:
    deposits = [(TODAY - timedelta(days=d), D(780)) for d in (7, 21, 35, 49)] + [(TODAY - timedelta(days=3), D(31))]
    days, amount = detect_paydays(deposits, TODAY, TODAY + timedelta(days=30))
    assert amount == D(780) and days == [TODAY + timedelta(days=7), TODAY + timedelta(days=21)]


def test_detects_a_monthly_paycheck_on_the_same_day() -> None:
    deposits = [(date(2026, m, 1), D(2100)) for m in (7, 8, 9, 10)]
    days, amount = detect_paydays(deposits, TODAY, date(2026, 12, 31))
    assert amount == D(2100) and days == [date(2026, 11, 1), date(2026, 12, 1)]


def test_projection_applies_bills_spending_income_and_scheduled_repayments() -> None:
    p = build_projection(
        slug="maya",
        first_name="Maya",
        age=20,
        today=TODAY,
        balance=D(680),
        bills=[(16, D(50), "Due today"), (20, D(35), "Phone")],
        deposits=[(TODAY - timedelta(days=d), D(780)) for d in (14, 28)],
        daily_spend=D(10),
        scheduled=[(TODAY + timedelta(days=2), D(-100), "Repay Sam")],
    )
    assert p.days[0] == (TODAY, D(630))  # bill due today counts; today's spending is already in the balance
    assert p.balance_on(TODAY + timedelta(days=2)) == D(630 - 20 - 100)
    assert p.balance_on(date(2026, 10, 20)) == D(630 - 40 - 100 - 35)
    assert p.next_payday == date(2026, 10, 30) and p.paycheck == D(780)

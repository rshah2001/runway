"""Readiness: the forecast calibrates before it trusts itself, and says how sure it is."""

from dataclasses import replace
from datetime import date, timedelta

import pytest

from app.forecast import engine, readiness, schedule, sources

TODAY = date(2026, 10, 16)


@pytest.mark.parametrize("persona", ["maya", "jordan", "sam"])
def test_four_months_of_history_is_confident(persona: str) -> None:
    r = engine.readiness(persona, TODAY)
    assert r.status == "confident" and r.paycheck_found and r.progress == 1.0
    assert r.spend_days == schedule.SPEND_WINDOW_DAYS


@pytest.mark.parametrize(
    ("history_days", "status"),
    [(5, "calibrating"), (12, "calibrating"), (20, "learning"), (30, "learning"), (45, "confident")],
)
def test_it_calibrates_then_learns_then_trusts_itself(history_days: int, status: str) -> None:
    assert engine.readiness("maya", TODAY, history_days=history_days).status == status


def test_progress_only_goes_up_as_history_grows() -> None:
    progress = [engine.readiness("maya", TODAY, history_days=d).progress for d in (5, 12, 20, 30, 45)]
    assert progress == sorted(progress) and progress[-1] == 1.0 and max(progress[:-1]) < 1.0


def test_reasons_say_where_it_is_in_plain_words() -> None:
    reasons = engine.readiness("maya", TODAY, history_days=12).reasons
    assert "I've watched 12 days of your money." in reasons
    assert any("1 of the 3 paychecks" in r for r in reasons)
    assert any("day 12 of 30" in r for r in reasons)


def test_no_paycheck_means_calibrating_however_long_the_history() -> None:
    data = sources.load("maya", TODAY)
    no_pay = replace(data, history=[t for t in data.history if t.kind != "deposit"])
    r = schedule.build(no_pay, TODAY).readiness
    assert r is not None and r.status == "calibrating" and r.paychecks_seen == 0
    assert any("no income in this forecast" in reason for reason in r.reasons)


def test_a_new_users_spending_rate_is_not_diluted_over_90_days() -> None:
    days = [TODAY - timedelta(days=i) for i in range(1, 21)]  # $10 every day for the 20 days we know about
    history = [sources.Txn(d, "purchase", -10.0, "Grocer", "Food", "Checking") for d in sorted(days)]
    new_user = sources.PersonaData("new", checking=500.0, savings=0.0, bills=[], history=history)
    assert schedule.build(new_user, TODAY).spend.expected(TODAY) == pytest.approx(10.0)  # not 200 / 90


def test_forecast_response_carries_readiness() -> None:
    f = engine.forecast(start=TODAY, persona="sam")
    assert f.readiness is not None and f.readiness.status == "confident"


def test_history_start_is_the_first_day_with_data() -> None:
    data = sources.recent(sources.load("jordan", TODAY), TODAY, 10)
    assert readiness.history_start(data) >= TODAY - timedelta(days=10)
    assert readiness.history_start(replace(data, history=[])) is None

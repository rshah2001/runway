"""The report card: replayed week-ahead forecasts scored against what actually happened."""

from datetime import date, timedelta

import pytest

from app.forecast import engine, report_card, schedule, sources

TODAY = date(2026, 10, 16)


def _steady_person(days: int) -> sources.PersonaData:
    """$10 of groceries every day from checking, nothing else: a perfectly predictable person."""
    history = [
        sources.Txn(TODAY - timedelta(days=i), "purchase", -10.0, "Grocer", "Food", "Checking")
        for i in range(days, 0, -1)
    ]
    return sources.PersonaData("steady", checking=1000.0, savings=0.0, bills=[], history=history)


def test_end_of_day_balances_work_back_from_today() -> None:
    balances = report_card.end_of_day_balances(_steady_person(30), TODAY)
    assert balances[TODAY - timedelta(days=1)] == 1000.0
    assert balances[TODAY - timedelta(days=2)] == 1010.0  # yesterday's $10 hadn't left yet


def test_a_predictable_person_gets_a_near_perfect_report_card() -> None:
    card = report_card.replay(_steady_person(60), TODAY, schedule.build, engine.forecast)
    assert card is not None and card.days_checked == report_card.WINDOW_DAYS
    assert card.mean_abs_error == pytest.approx(0, abs=0.05)


def test_no_report_card_without_enough_history_to_have_forecast() -> None:
    assert report_card.replay(_steady_person(10), TODAY, schedule.build, engine.forecast) is None


def test_readiness_reports_its_own_recent_accuracy() -> None:
    r = engine.readiness("maya", TODAY)
    assert r.rolling_error is not None and r.rolling_error_days == report_card.WINDOW_DAYS
    assert any("7-day-ahead forecasts were off by" in reason for reason in r.reasons)


def test_the_replay_never_peeks_at_the_day_it_predicts() -> None:
    """Changing a day's spending must not change the forecast made a week before it."""
    data = _steady_person(60)
    spiky = sources.PersonaData(
        "spiky",
        checking=data.checking - 500,
        savings=0.0,
        bills=[],
        history=[
            *data.history[:-1],
            sources.Txn(TODAY - timedelta(days=1), "purchase", -510.0, "TV", "Shopping", "Checking"),
        ],
    )
    card = report_card.replay(spiky, TODAY, schedule.build, engine.forecast)
    assert card is not None and card.mean_abs_error == pytest.approx(500 / report_card.WINDOW_DAYS, abs=0.05)

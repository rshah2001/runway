"""The safety net reads the forecast engine (one forecast for the whole app). Offline demo data."""

from datetime import date, timedelta
from decimal import Decimal

from app.cashflow import next_paycheck, projection_for
from app.forecast import engine
from app.schemas import ForecastEvent

TODAY = date(2026, 10, 16)  # a Friday


def test_projection_matches_the_engine_exactly() -> None:
    p = projection_for("jordan", first_name="Jordan", age=40, today=TODAY)
    f = engine.forecast(days=34, persona="jordan", start=TODAY)
    assert [(d, float(b)) for d, b in p.days] == [(pt.date, pt.balance) for pt in f.points]


def test_next_paycheck_comes_from_the_engines_schedule() -> None:
    payday, amount = next_paycheck(engine.schedule_for("maya", TODAY), TODAY)
    assert payday == TODAY + timedelta(days=7) and amount == Decimal("780.0")  # biweekly Friday, never today


def test_scheduled_repayments_move_the_projection() -> None:
    due = TODAY + timedelta(days=3)
    base = projection_for("sam", first_name="Sam", age=60, today=TODAY)
    paid = projection_for(
        "sam",
        first_name="Sam",
        age=60,
        today=TODAY,
        scheduled=[ForecastEvent(date=due, amount=100, label="Maya pays you back", kind="transfer")],
    )
    assert paid.balance_on(due) - base.balance_on(due) == Decimal(100)
    assert paid.balance_on(due - timedelta(days=1)) == base.balance_on(due - timedelta(days=1))


def test_maya_demo_dip_is_208_on_the_engine_every_day() -> None:
    """The seed tunes Maya's balance against the engine itself, so chat, charts and the safety net
    all see the same $208 low before payday — whatever day the demo runs."""
    for offset in range(14):
        today = TODAY + timedelta(days=offset)
        p = projection_for("maya", first_name="Maya", age=20, today=today)
        assert abs(p.low(today, p.next_payday)[1] - Decimal("208")) <= Decimal("0.01"), today


def test_safety_net_inputs_never_fall_back_to_demo_data(monkeypatch) -> None:
    """Money decisions must not run on made-up balances: strict loads fail instead of falling back."""
    import pytest

    from app.forecast import sources

    with pytest.raises(sources.LiveDataUnavailable):  # tests run in demo mode
        sources.load("maya", TODAY, strict=True)

    class Live:
        live = True

    monkeypatch.setattr(sources, "get_settings", lambda: Live())
    monkeypatch.setattr(sources, "_load_live", lambda p, t: (_ for _ in ()).throw(ConnectionError("db down")))
    with pytest.raises(sources.LiveDataUnavailable):
        sources.load("maya", TODAY, strict=True)
    assert sources.load("maya", TODAY).slug == "maya"  # the chat path still falls back and keeps answering

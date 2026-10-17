"""The forecast's range: a p10–p90 band from how much everyday spending actually varies."""

from datetime import date

import pytest

from app.forecast import band, engine
from app.forecast.schedule import Schedule
from app.forecast.spend_model import SpendProfile

TODAY = date(2026, 10, 16)


def test_every_point_has_a_range_around_the_expected_balance() -> None:
    f = engine.forecast(start=TODAY, persona="maya")
    assert all(p.balance_low is not None and p.balance_high is not None for p in f.points)
    assert all(p.balance_low <= p.balance <= p.balance_high for p in f.points)


def test_the_range_widens_the_further_out_it_looks() -> None:
    points = engine.forecast(days=60, start=TODAY, persona="jordan").points
    width = [p.balance_high - p.balance_low for p in points]
    assert width[60] > width[30] > width[7] > width[0]


def test_same_history_same_band() -> None:
    a, b = (engine.forecast(start=TODAY, persona="sam") for _ in range(2))
    assert [p.balance_low for p in a.points] == [p.balance_low for p in b.points]


def test_cautious_low_is_the_lowest_p10_and_is_below_the_expected_low() -> None:
    f = engine.forecast(start=TODAY, persona="maya")
    assert f.cautious_low is not None
    assert f.cautious_low.balance_low == min(p.balance_low for p in f.points)
    assert f.cautious_low.balance_low < f.low.balance


def test_quantiles_are_of_the_total_not_summed_per_day() -> None:
    daily = (0.0, 0.0, 10.0, 0.0, 50.0, 5.0, 0.0) * 13  # ~13 weeks of lumpy spending
    one_day_extra = band.spread(daily, 1)[0][0]
    month_extra = band.spread(daily, 30)[29][0]
    assert month_extra < 30 * one_day_extra  # big and small days average out over a month


def test_steady_spending_has_almost_no_range() -> None:
    down, up = band.spread((20.0,) * 90, 30)[29]
    assert down == pytest.approx(0, abs=0.01) and up == pytest.approx(0, abs=0.01)


def test_no_history_means_no_range_and_no_cautious_low() -> None:
    f = engine.forecast(start=TODAY, schedule=Schedule(start_balance=500.0, spend=SpendProfile((10.0,) * 7)))
    assert f.cautious_low is None and all(p.balance_low is None for p in f.points)
    assert band.spread((), 5) == ((0.0, 0.0),) * 5


def test_horizons_share_a_cached_band() -> None:
    daily = tuple(float(i % 9) for i in range(90))
    assert band.spread(daily, 20) == band.spread(daily, 31)[:20]

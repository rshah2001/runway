"""The forecast's range: a p5–p90 band from how much everyday spending actually varies."""

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


def test_cautious_low_is_the_lowest_p5_and_is_below_the_expected_low() -> None:
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


# ---------- calibration (ml/calibrate_band.py → band_calibration.json) ----------


def test_calibration_file_is_shipped_and_only_widens() -> None:
    cal = band._calibration()
    assert cal["history_days"] == sorted(cal["history_days"])
    assert all(f >= 1.0 for f in cal["cautious"] + cal["optimistic"])


def test_widening_interpolates_between_calibrated_lengths() -> None:
    cal = band._calibration()
    (x0, x1), (h0, h1) = cal["history_days"][:2], cal["cautious"][:2]
    assert band.widening(x0)[0] == pytest.approx(h0)
    assert band.widening((x0 + x1) // 2)[0] == pytest.approx(h0 + (h1 - h0) * ((x0 + x1) // 2 - x0) / (x1 - x0))
    assert band.widening(5) == band.widening(x0)  # shorter histories use the shortest calibrated factor
    assert band.widening(365) == band.widening(cal["history_days"][-1])


def test_calibrated_spread_is_the_raw_bootstrap_widened() -> None:
    daily = tuple(float(i % 9) for i in range(90))
    cautious, optimistic = band.widening(90)
    for (down, up), (raw_down, raw_up) in zip(band.spread(daily, 30), band.raw_spread(daily, 30), strict=True):
        assert down == pytest.approx(raw_down * cautious) and up == pytest.approx(raw_up * optimistic)


def test_missing_calibration_file_means_no_widening(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(band, "CALIBRATION_FILE", tmp_path / "missing.json")
    band._calibration.cache_clear()
    try:
        assert band.widening(90) == (1.0, 1.0)
    finally:
        band._calibration.cache_clear()

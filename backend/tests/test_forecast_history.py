"""The saved track record: snapshot rows, the scoring math, the once-a-day guard and the replay fallback.

None of this needs a database: the pure parts are tested directly, and the database edges are
replaced with fakes, the same way CI runs (RUNWAY_FORCE_MOCK=1, no DATABASE_URL).
"""

from datetime import date, timedelta

import pytest

from app import forecast_history
from app.forecast import engine, readiness, report_card, snapshots
from app.schemas import Forecast, ForecastPoint

TODAY = date(2026, 10, 16)


def _forecast(days: int, *, band: bool = True) -> Forecast:
    points = [
        ForecastPoint(
            date=TODAY + timedelta(days=i),
            balance=1000.0 - 10 * i,
            balance_low=(990.0 - 10 * i) if band else None,
            balance_high=(1010.0 - 10 * i) if band else None,
        )
        for i in range(days + 1)
    ]
    return Forecast(points=points, low=points[-1], safe_floor=100.0, events=[])


# ---------- snapshot rows ----------


def test_one_row_per_day_with_its_band_and_lead() -> None:
    rows = snapshots.rows_from_forecast("maya", TODAY, _forecast(3), "v1")
    assert [r["lead_days"] for r in rows] == [1, 2, 3, 4]  # day 1 = the end of the day it was made
    assert rows[0] == {
        "persona_slug": "maya",
        "made_on": TODAY,
        "target_date": TODAY,
        "lead_days": 1,
        "balance": 1000.0,
        "balance_low": 990.0,
        "balance_high": 1010.0,
        "engine_version": "v1",
        "readiness": None,
    }


def test_only_the_snapshot_horizon_is_kept() -> None:
    rows = snapshots.rows_from_forecast("maya", TODAY, _forecast(60), "v1")
    assert len(rows) == snapshots.SNAPSHOT_DAYS and rows[-1]["lead_days"] == snapshots.SNAPSHOT_DAYS


def test_lead_matches_the_replays_convention() -> None:
    """The replay's LEAD_DAYS forecast is made on target - (LEAD_DAYS - 1): the same lead here."""
    target = TODAY
    assert snapshots.lead_days(target - timedelta(days=report_card.LEAD_DAYS - 1), target) == report_card.LEAD_DAYS


def test_snapshot_rows_are_the_forecast_the_app_shows() -> None:
    fc = engine.forecast(days=snapshots.SNAPSHOT_DAYS, persona="maya", start=TODAY)
    rows = snapshots.rows_from_forecast("maya", TODAY, fc, engine.ENGINE_VERSION)
    assert [r["balance"] for r in rows] == [p.balance for p in fc.points[: snapshots.SNAPSHOT_DAYS]]
    assert all(r["balance_low"] is not None and r["readiness"] == "confident" for r in rows)


# ---------- scoring ----------


def test_score_is_the_dollar_error_and_whether_it_landed_in_the_band() -> None:
    assert snapshots.score(100.0, 90.0, 120.0, 95.0) == snapshots.Score(abs_error=5.0, in_band=True)
    assert snapshots.score(100.0, 90.0, 120.0, 130.5) == snapshots.Score(abs_error=30.5, in_band=False)
    assert snapshots.score(100.0, 90.0, 120.0, 90.0).in_band  # the edges count as inside
    assert snapshots.score(100.0, None, None, 80.0) == snapshots.Score(abs_error=20.0, in_band=None)


def _saved(target: date, balance: float, low: float | None, high: float | None, actual: float | None = None) -> dict:
    made_on = target - timedelta(days=6)
    return {
        "persona_slug": "maya",
        "made_on": made_on,
        "target_date": target,
        "balance": balance,
        "balance_low": low,
        "balance_high": high,
        "actual": actual,
    }


def test_rescore_scores_only_days_with_a_known_actual() -> None:
    d1, d2, d3 = TODAY - timedelta(days=3), TODAY - timedelta(days=2), TODAY - timedelta(days=1)
    rows = [_saved(d1, 500, 450, 550), _saved(d2, 500, 450, 550), _saved(d3, 500, None, None)]
    updates = snapshots.rescore(rows, {d1: 470.0, d3: 400.0})  # d2's actual isn't known
    assert [(u["target_date"], u["abs_error"], u["in_band"]) for u in updates] == [(d1, 30.0, True), (d3, 100.0, None)]


def test_rescore_writes_nothing_twice_but_corrects_a_changed_past() -> None:
    d = TODAY - timedelta(days=1)
    assert snapshots.rescore([_saved(d, 500, 450, 550, actual=470)], {d: 470.0}) == []
    (update,) = snapshots.rescore([_saved(d, 500, 450, 550, actual=470)], {d: 420.0})  # a late purchase posted
    assert update["actual"] == 420.0 and update["abs_error"] == 80.0 and update["in_band"] is False


def _day(days: int, error_sum: float, banded: int, inside: int) -> dict:
    return {"days_scored": days, "abs_error_sum": error_sum, "banded": banded, "in_band": inside}


def test_combine_is_the_mean_absolute_error_and_band_coverage_over_all_days() -> None:
    """Hand-made: 8 scored days, errors adding up to $200, 6 of the 8 inside the band."""
    daily = [_day(1, 10, 1, 1), _day(1, 30, 1, 0), *[_day(1, 25, 1, 1)] * 5, _day(1, 35, 1, 0)]
    card = snapshots.combine(daily)
    assert card is not None and card.source == "saved"
    assert card.days_checked == 8 and card.mean_abs_error == 25.0 and card.band_coverage == 0.75


def test_combine_needs_enough_scored_days() -> None:
    assert snapshots.combine([_day(1, 10, 1, 1)] * (report_card.MIN_DAYS_CHECKED - 1)) is None


def test_combine_without_any_band_has_no_coverage() -> None:
    card = snapshots.combine([_day(1, 10, 0, 0)] * report_card.MIN_DAYS_CHECKED)
    assert card is not None and card.band_coverage is None


def test_the_window_checks_the_same_days_the_replay_does() -> None:
    first, last = snapshots.made_on_window(TODAY, lead=7, days=14)
    # 7-day-ahead forecasts for target days TODAY-14 … TODAY-1 were made 6 days before each
    assert first == TODAY - timedelta(days=14 + 6) and last == TODAY - timedelta(days=1 + 6)


# ---------- once a day ----------


def test_daily_once_guard() -> None:
    once = snapshots.DailyOnce()
    assert once.due("maya", TODAY)
    once.mark("maya", TODAY)
    assert not once.due("maya", TODAY) and once.due("sam", TODAY)
    assert once.due("maya", TODAY + timedelta(days=1))


@pytest.fixture
def live_history(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """forecast_history.run as if live, with the database edges faked; returns the call log."""
    calls: list[str] = []
    monkeypatch.setattr(forecast_history, "_once", snapshots.DailyOnce())
    monkeypatch.setattr(forecast_history, "get_settings", lambda: type("S", (), {"live": True})())
    monkeypatch.setattr(forecast_history, "_persona_slugs", lambda: ["maya", "sam"])
    monkeypatch.setattr(forecast_history, "_refresh_accuracy", lambda: calls.append("refresh"))

    def record_and_score(slug: str, today: date) -> tuple[int, int]:
        calls.append(f"{slug}:{today.isoformat()}")
        return snapshots.SNAPSHOT_DAYS, 3

    monkeypatch.setattr(forecast_history, "record_and_score", record_and_score)
    return calls


def test_writes_at_most_once_a_day_per_persona(live_history: list[str]) -> None:
    first = forecast_history.run(TODAY)
    assert first == {"personas": 2, "saved": 2 * snapshots.SNAPSHOT_DAYS, "scored": 6}
    assert forecast_history.run(TODAY) == {"personas": 0, "saved": 0, "scored": 0}  # every later pass today
    forecast_history.run(TODAY + timedelta(days=1))
    assert live_history == [
        "maya:2026-10-16",
        "sam:2026-10-16",
        "refresh",
        "maya:2026-10-17",
        "sam:2026-10-17",
        "refresh",
    ]


def test_a_failed_persona_is_retried_and_does_not_stop_the_others(
    live_history: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts: list[str] = []

    def flaky(slug: str, today: date) -> tuple[int, int]:
        attempts.append(slug)
        if slug == "maya" and attempts.count("maya") == 1:
            raise RuntimeError("database blip")
        return 1, 0

    monkeypatch.setattr(forecast_history, "record_and_score", flaky)
    assert forecast_history.run(TODAY)["personas"] == 1
    assert forecast_history.run(TODAY)["personas"] == 1  # maya again; sam already done
    assert attempts == ["maya", "sam", "maya"]


def test_offline_it_does_nothing() -> None:
    assert forecast_history.run(TODAY) == {}  # CI: RUNWAY_FORCE_MOCK=1, no database


# ---------- the report card: saved first, replay as the fallback ----------


def test_offline_the_report_card_is_the_replay() -> None:
    r = engine.readiness("maya", TODAY)
    assert r.rolling_error_source == "replay" and r.band_coverage is None
    assert any(reason.startswith("Replayed on your history, my 7-day-ahead forecasts") for reason in r.reasons)


def test_saved_forecasts_replace_the_replay_when_there_are_enough(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(snapshots, "_live", lambda: True)
    monkeypatch.setattr(snapshots, "_fetch_daily", lambda *_: [_day(1, 30, 1, 1)] * 9 + [_day(1, 30, 1, 0)])
    r = engine.readiness("maya", TODAY)
    assert r.rolling_error == 30.0 and r.rolling_error_days == 10
    assert r.rolling_error_source == "saved" and r.band_coverage == 0.9
    assert (
        "The 7-day-ahead forecasts I saved were off by $30.00 on average over the last 10 days I could check, "
        "and your real balance landed inside my range 90% of the time." in r.reasons
    )


@pytest.mark.parametrize("fetch", ["too_few", "broken"])
def test_falls_back_to_the_replay(monkeypatch: pytest.MonkeyPatch, fetch: str) -> None:
    def fetch_daily(*_: object) -> list[dict]:
        if fetch == "broken":
            raise RuntimeError("database down")
        return [_day(1, 30, 1, 1)] * (report_card.MIN_DAYS_CHECKED - 1)

    monkeypatch.setattr(snapshots, "_live", lambda: True)
    monkeypatch.setattr(snapshots, "_fetch_daily", fetch_daily)
    r = engine.readiness("maya", TODAY)
    assert r.rolling_error_source == "replay" and r.rolling_error_days == report_card.WINDOW_DAYS


def test_a_shortened_history_never_borrows_the_saved_record(monkeypatch: pytest.MonkeyPatch) -> None:
    """The demo's "day 45" story replays its own short past; the saved record is about the real one."""
    monkeypatch.setattr(snapshots, "_live", lambda: True)
    monkeypatch.setattr(snapshots, "_fetch_daily", lambda *_: [_day(1, 30, 1, 1)] * 10)
    assert engine.readiness("maya", TODAY, history_days=45).rolling_error_source != "saved"


def test_track_record_wording_says_which_it_is() -> None:
    replayed = report_card.ReportCard(mean_abs_error=38.2, days_checked=14)
    saved = report_card.ReportCard(mean_abs_error=31.0, days_checked=9, source="saved", band_coverage=None)
    assert readiness.track_record(replayed) == (
        "Replayed on your history, my 7-day-ahead forecasts were off by $38.20 on average over the last 14 days."
    )
    assert readiness.track_record(saved) == (
        "The 7-day-ahead forecasts I saved were off by $31.00 on average over the last 9 days I could check."
    )

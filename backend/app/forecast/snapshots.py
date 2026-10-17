"""The forecast's saved track record — owner: Patil-Hemangi.

Every day Runway keeps the forecast it showed each persona (the next SNAPSHOT_DAYS days, as the app's
/forecast returns them) in the `forecast_snapshots` hypertable. Once a day has passed, its real
end-of-day balance is written next to every forecast made for it, with the error and whether it landed
inside the predicted band. The `forecast_accuracy_daily` continuous aggregate adds those up, and the
report card reads it: "my saved 7-day-ahead forecasts were off by $31 on average over the last 14 days".

Unlike the replay in `report_card`, this proves what the app actually showed at the time. It needs
MIN_DAYS_CHECKED scored days before it says anything; until then the report card falls back to the
replay and says so. Everything here except `saved_card`'s database read is pure, so it is unit-tested
without a database.
"""

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from app.config import get_settings
from app.forecast.report_card import LEAD_DAYS, MIN_DAYS_CHECKED, WINDOW_DAYS, ReportCard
from app.schemas import Forecast

log = logging.getLogger(__name__)

SNAPSHOT_DAYS = 30  # the app's default horizon: everything someone could have planned around
TRACKED_LEADS = (1, 7, 14)  # day-ahead horizons the accuracy aggregate keeps (see db/schema.py)
RESCORE_DAYS = 35  # past target days re-checked each day, so a late-posted purchase still corrects a score

Row = dict[str, Any]


def lead_days(made_on: date, target: date) -> int:
    """How far ahead a forecast was. Day 1 is the end of the day it was made, the same convention as
    the replay's LEAD_DAYS, so the saved and replayed report cards measure the same thing."""
    return (target - made_on).days + 1


def rows_from_forecast(slug: str, made_on: date, fc: Forecast, engine_version: str) -> list[Row]:
    """The `forecast_snapshots` rows for one forecast: one per day, for the first SNAPSHOT_DAYS days."""
    status = fc.readiness.status if fc.readiness else None
    return [
        {
            "persona_slug": slug,
            "made_on": made_on,
            "target_date": p.date,
            "lead_days": lead_days(made_on, p.date),
            "balance": p.balance,
            "balance_low": p.balance_low,
            "balance_high": p.balance_high,
            "engine_version": engine_version,
            "readiness": status,
        }
        for p in fc.points
        if 1 <= lead_days(made_on, p.date) <= SNAPSHOT_DAYS
    ]


@dataclass(frozen=True)
class Score:
    abs_error: float
    in_band: bool | None  # None when the forecast had no band to land in


def score(balance: float, low: float | None, high: float | None, actual: float) -> Score:
    """How one forecast day did: its dollar error, and whether the real balance was inside its band."""
    in_band = None if low is None or high is None else low <= actual <= high
    return Score(abs_error=round(abs(balance - actual), 2), in_band=in_band)


def rescore(rows: Iterable[Row], actual: Mapping[date, float]) -> list[Row]:
    """Score updates for saved rows whose target day now has a known actual balance. Rows already
    scored with the same actual are skipped, so a daily rerun writes nothing unless the past changed."""
    updates = []
    for r in rows:
        real = actual.get(r["target_date"])
        if real is None or (r.get("actual") is not None and float(r["actual"]) == real):
            continue
        low, high = r.get("balance_low"), r.get("balance_high")
        s = score(float(r["balance"]), None if low is None else float(low), None if high is None else float(high), real)
        updates.append(
            {
                "persona_slug": r["persona_slug"],
                "made_on": r["made_on"],
                "target_date": r["target_date"],
                "actual": real,
                "abs_error": s.abs_error,
                "in_band": s.in_band,
            }
        )
    return updates


def made_on_window(today: date, lead: int = LEAD_DAYS, days: int = WINDOW_DAYS) -> tuple[date, date]:
    """The `made_on` days whose `lead`-day-ahead forecast was for one of the last `days` days — the
    same days the replay checks — as an inclusive range."""
    first_target, last_target = today - timedelta(days=days), today - timedelta(days=1)
    back = timedelta(days=lead - 1)
    return first_target - back, last_target - back


def combine(daily: Iterable[Row], lead: int = LEAD_DAYS) -> ReportCard | None:
    """One report card from `forecast_accuracy_daily` rows (sums and counts per day). None until
    MIN_DAYS_CHECKED days have been scored: a shorter average says more about luck than the forecast."""
    rows = list(daily)
    days = sum(int(r["days_scored"]) for r in rows)
    if days < MIN_DAYS_CHECKED:
        return None
    error = sum(float(r["abs_error_sum"]) for r in rows)
    banded = sum(int(r["banded"]) for r in rows)
    inside = sum(int(r["in_band"]) for r in rows)
    return ReportCard(
        mean_abs_error=round(error / days, 2),
        days_checked=days,
        lead_days=lead,
        source="saved",
        band_coverage=round(inside / banded, 2) if banded else None,
    )


class DailyOnce:
    """Remembers which personas already had today's snapshot written, so the background pass (every
    few minutes) does the work at most once a day per persona. The database's primary key is the real
    guarantee; this only saves the forecast and the query on every other pass of the day."""

    def __init__(self) -> None:
        self._done: dict[str, date] = {}

    def due(self, slug: str, today: date) -> bool:
        return self._done.get(slug) != today

    def mark(self, slug: str, today: date) -> None:
        self._done[slug] = today


def _live() -> bool:
    return get_settings().live


def _fetch_daily(slug: str, first: date, last: date, lead: int) -> list[Row]:
    from app.db import forecast_repo, pool  # imported lazily: offline runs never need a database driver

    with pool.connection() as conn:
        return forecast_repo.accuracy_daily(conn, slug, lead, first, last)


def saved_card(slug: str, today: date, lead: int = LEAD_DAYS) -> ReportCard | None:
    """The report card from saved, scored forecasts, or None when there isn't one yet — offline, too
    few scored days, or the database read failed (the caller then replays instead)."""
    if not _live():
        return None
    first, last = made_on_window(today, lead)
    try:
        return combine(_fetch_daily(slug, first, last, lead), lead)
    except Exception:  # the report card is informational: never let it break a forecast
        log.warning("saved report card unavailable for %s, replaying instead", slug, exc_info=True)
        return None

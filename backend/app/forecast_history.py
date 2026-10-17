"""Save each day's forecast in Tiger Data and score the ones whose day has passed — live mode only.

Called from the API's background pass right after the Nessie sync, so it works on fresh data. Each
persona is handled at most once a day (snapshots.DailyOnce; the table's primary key backs it up), and
a failure for one persona is logged and retried on the next pass without touching the others. The
report card then reads the results through `forecast_accuracy_daily` (see forecast/snapshots).
"""

import logging
from datetime import date, timedelta

from app.config import get_settings
from app.forecast import engine, report_card, snapshots, sources

log = logging.getLogger(__name__)

_once = snapshots.DailyOnce()


def todays_rows(slug: str, today: date) -> list[dict]:
    """Today's forecast exactly as GET /forecast shows it (same data, engine and 30-day horizon, so
    even the band is the same), as snapshot rows. `strict`: a failed read must not save demo data."""
    data = sources.load(slug, today, strict=True)
    fc = engine.forecast(days=snapshots.SNAPSHOT_DAYS, start=today, schedule=engine.schedule_from(data, today))
    return snapshots.rows_from_forecast(slug, today, fc, engine.ENGINE_VERSION)


def actual_balances(slug: str, today: date) -> dict[date, float]:
    """The real end-of-day checking balance for each day before today, worked back from the live
    balance the same way the replay does. History is read through the end of today, so today's own
    transactions — already in the live balance — are subtracted too, and yesterday's figure is right."""
    tomorrow = today + timedelta(days=1)
    data = sources.load(slug, tomorrow, strict=True)
    return {d: b for d, b in report_card.end_of_day_balances(data, tomorrow).items() if d < today}


def record_and_score(slug: str, today: date) -> tuple[int, int]:
    """Save today's forecast for one persona (unless it already is) and score every saved forecast for
    the last RESCORE_DAYS days. Returns (rows saved, rows scored)."""
    from app.db import forecast_repo, pool  # imported lazily: offline runs never need a database driver

    with pool.connection() as conn:
        already = forecast_repo.has_snapshot(conn, slug, today)
    rows = [] if already else todays_rows(slug, today)  # computed outside the connection: it opens its own
    actual = actual_balances(slug, today)
    with pool.connection() as conn:
        saved = forecast_repo.save_snapshots(conn, rows)
        due = forecast_repo.snapshots_due(
            conn, slug, today - timedelta(days=snapshots.RESCORE_DAYS), today, snapshots.SNAPSHOT_DAYS
        )
        scored = forecast_repo.save_scores(conn, snapshots.rescore(due, actual))
        conn.commit()
    return saved, scored


def _persona_slugs() -> list[str]:
    from app.db import pool, repo

    with pool.connection() as conn:
        return [p["slug"] for p in repo.personas(conn)]


def _refresh_accuracy() -> None:
    from app.db import pool
    from app.db import schema as db_schema

    with pool.connection() as conn:
        db_schema.refresh_forecast_accuracy(conn)


def run(today: date | None = None) -> dict[str, int]:
    """One background pass: every persona not yet done today. Returns totals, for the log."""
    if not get_settings().live:
        return {}
    today = today or sources.local_today()
    totals = {"personas": 0, "saved": 0, "scored": 0}
    for slug in _persona_slugs():
        if not _once.due(slug, today):
            continue
        try:
            saved, scored = record_and_score(slug, today)
        except Exception:  # one persona's bad day must not stop the others, or the safety net after us
            log.exception("forecast history: %s failed, retrying next pass", slug)
            continue
        _once.mark(slug, today)
        totals["personas"] += 1
        totals["saved"] += saved
        totals["scored"] += scored
    if totals["scored"]:
        _refresh_accuracy()  # so the new scores count in the report card straight away
    if totals["personas"]:
        log.info("forecast history: %s", totals)
    return totals

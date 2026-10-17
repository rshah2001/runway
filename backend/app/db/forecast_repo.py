"""Queries for the forecast's saved track record (`forecast_snapshots`, `forecast_accuracy_daily`)."""

from datetime import date, timedelta
from typing import Any

import psycopg

Row = dict[str, Any]


def has_snapshot(conn: psycopg.Connection, slug: str, made_on: date) -> bool:
    """Whether today's forecast for this persona is already saved (e.g. before an API restart)."""
    row = conn.execute(
        "SELECT 1 FROM forecast_snapshots WHERE persona_slug = %s AND made_on = %s LIMIT 1", (slug, made_on)
    ).fetchone()
    return row is not None


def save_snapshots(conn: psycopg.Connection, rows: list[Row]) -> int:
    """Save one day's forecast. A rerun the same day never duplicates and never rewrites: the first
    forecast of the day is the one people planned around, and a later one would already know part of
    the day it predicts, flattering its own score."""
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO forecast_snapshots (persona_slug, made_on, target_date, lead_days, balance, balance_low,
                                               balance_high, engine_version, readiness)
               VALUES (%(persona_slug)s, %(made_on)s, %(target_date)s, %(lead_days)s, %(balance)s, %(balance_low)s,
                       %(balance_high)s, %(engine_version)s, %(readiness)s)
               ON CONFLICT (persona_slug, made_on, target_date) DO NOTHING""",
            rows,
        )
    return len(rows)


def snapshots_due(conn: psycopg.Connection, slug: str, first_target: date, before: date, max_lead: int) -> list[Row]:
    """Saved forecasts for target days in [first_target, before), with any score they already have.
    The made_on bound lets TimescaleDB skip every chunk that can't hold such a forecast."""
    return conn.execute(
        """SELECT persona_slug, made_on, target_date, balance, balance_low, balance_high, actual
           FROM forecast_snapshots
           WHERE persona_slug = %s AND target_date >= %s AND target_date < %s
             AND made_on >= %s AND made_on < %s""",
        (slug, first_target, before, first_target - timedelta(days=max_lead), before),
    ).fetchall()


def save_scores(conn: psycopg.Connection, updates: list[Row]) -> int:
    """Write what really happened next to each saved forecast (see forecast/snapshots.rescore)."""
    if not updates:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            """UPDATE forecast_snapshots
               SET actual = %(actual)s, abs_error = %(abs_error)s, in_band = %(in_band)s, scored_at = now()
               WHERE persona_slug = %(persona_slug)s AND made_on = %(made_on)s AND target_date = %(target_date)s""",
            updates,
        )
    return len(updates)


def accuracy_daily(conn: psycopg.Connection, slug: str, lead: int, first: date, last: date) -> list[Row]:
    """Per-day sums and counts from the continuous aggregate for forecasts made in [first, last]."""
    return conn.execute(
        """SELECT day, days_scored, abs_error_sum, banded, in_band FROM forecast_accuracy_daily
           WHERE persona_slug = %s AND lead_days = %s AND day >= %s AND day <= %s ORDER BY day""",
        (slug, lead, first, last),
    ).fetchall()

"""Per-person money preferences — for now, the amount someone wants to keep in checking.

Runway used one cushion for everyone ($300). People differ: one person gets anxious under $100,
another is calm near $0, a retiree may want $1,000 untouched. This amount is what every "am I
okay?" answer is measured against for that person: the forecast's dashed line and status, the
agent's answers, "spare money today", when the safety net steps in, how much it asks for, and —
for a lender — how far their own balance may go while helping someone else.

Live: stored in Tiger Data (`money_preferences`). Demo/offline: kept in memory, so the screens and
tests behave the same. Anyone who never set one gets DEFAULT_FLOOR.
"""

import logging

from app.config import get_settings

log = logging.getLogger(__name__)

DEFAULT_FLOOR = 300.0
MAX_FLOOR = 5000.0  # a cushion, not a savings goal; also keeps a typo from freezing every bridge

_demo: dict[str, float] = {}  # offline / demo mode only


class FloorOutOfRange(ValueError):
    """The requested amount isn't between $0 and MAX_FLOOR."""


def check(amount: float) -> float:
    """Validate and round an amount to keep (whole cents)."""
    if not 0 <= amount <= MAX_FLOOR:
        raise FloorOutOfRange(f"Pick an amount from $0 to ${MAX_FLOOR:,.0f}.")
    return round(float(amount), 2)


def floor(slug: str, conn=None, *, strict: bool = False) -> float:
    """The amount `slug` keeps. A failed read falls back to the default for screens; with
    `strict=True` (anything that moves money) it raises instead — acting on a guessed cushion could
    move family money someone didn't need, or hold back money they did."""
    if not get_settings().live:
        return _demo.get(slug, DEFAULT_FLOOR)
    if strict:
        if conn is not None:
            return _read(conn, slug)
        from app.db import pool

        with pool.connection() as c:
            return _read(c, slug)
    try:
        if conn is not None:
            return _read(conn, slug)
        from app.db import pool

        with pool.connection() as c:
            return _read(c, slug)
    except Exception:
        log.exception("prefs: couldn't read the floor for %s, using the default", slug)
        return DEFAULT_FLOOR


def _read(conn, slug: str) -> float:
    from app.db import repo

    value = repo.safe_floor(conn, slug)
    return DEFAULT_FLOOR if value is None else float(value)


def set_floor(slug: str, amount: float) -> float:
    """Save the amount `slug` keeps; returns it as stored."""
    amount = check(amount)
    if not get_settings().live:
        _demo[slug] = amount
        return amount
    from app.db import pool, repo

    with pool.connection() as conn:
        repo.set_safe_floor(conn, slug, amount)
        conn.commit()
    return amount


def reset(slugs: list[str] | tuple[str, ...], conn=None) -> None:
    """Back to the default for these people (the demo reset uses this)."""
    for s in slugs:
        _demo.pop(s, None)
    if conn is not None and get_settings().live:
        from app.db import repo

        repo.clear_safe_floors(conn, list(slugs))

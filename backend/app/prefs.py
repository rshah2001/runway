"""Per-person money preferences: the amount someone keeps in checking, and two on/off settings.

Runway used one cushion for everyone ($300). People differ: one person gets anxious under $100,
another is calm near $0, a retiree may want $1,000 untouched. This amount is what every "am I
okay?" answer is measured against for that person: the forecast's dashed line and status, the
agent's answers, "spare money today", when the safety net steps in, how much it asks for, and —
for a lender — how far their own balance may go while helping someone else.

The on/off settings answer the two reasons people in our buyer panel said no:
  * alerts_only — "I avoid looking at my balance." Today shows one calm line and speaks up only
    before a dip, with the fix; the numbers stay one tap away.
  * family_cover — "I'd be embarrassed." Off means family limits never move money to you, even if
    someone set one; on, they only ever see what they covered and when it comes back.

Live: stored in Tiger Data (`money_preferences`). Demo/offline: kept in memory, so the screens and
tests behave the same. Anyone who never set one gets the default.
"""

import logging

from app.config import get_settings

log = logging.getLogger(__name__)

DEFAULT_FLOOR = 300.0
MAX_FLOOR = 5000.0  # a cushion, not a savings goal; also keeps a typo from freezing every bridge

# discreet_notifications: lock-screen previews say "Runway has an update", never an amount or a name
DEFAULTS = {"alerts_only": False, "family_cover": True, "discreet_notifications": True}

_demo: dict[str, float] = {}  # offline / demo mode only
_demo_settings: dict[tuple[str, str], bool] = {}


def default_floor(slug: str) -> float:
    """What someone keeps until they choose their own amount: their persona's own cushion if it has
    one (Jordan keeps $1,500 for a family of four), otherwise $300."""
    from seed.personas import PERSONAS  # local: seed imports app modules

    spec = next((p for p in PERSONAS if p.slug == slug), None)
    return spec.cushion if spec is not None and spec.cushion is not None else DEFAULT_FLOOR


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
        return _demo.get(slug, default_floor(slug))
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
        return default_floor(slug)


def _read(conn, slug: str) -> float:
    from app.db import repo

    value = repo.safe_floor(conn, slug)
    return default_floor(slug) if value is None else float(value)


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


def setting(slug: str, name: str, conn=None, *, strict: bool = False) -> bool:
    """An on/off setting for `slug`. Like `floor`: a failed read gives the default on screens, and
    raises with `strict=True` (family_cover decides whether family money moves)."""
    if name not in DEFAULTS:
        raise ValueError(f"unknown setting {name!r}")
    if not get_settings().live:
        return _demo_settings.get((slug, name), DEFAULTS[name])
    try:
        if conn is not None:
            value = _read_setting(conn, slug, name)
        else:
            from app.db import pool

            with pool.connection() as c:
                value = _read_setting(c, slug, name)
    except Exception:
        if strict:
            raise
        log.exception("prefs: couldn't read %s for %s, using the default", name, slug)
        return DEFAULTS[name]
    return DEFAULTS[name] if value is None else value


def _read_setting(conn, slug: str, name: str) -> bool | None:
    from app.db import repo

    return repo.setting(conn, slug, name)


def set_setting(slug: str, name: str, on: bool) -> bool:
    """Save one on/off setting for `slug`; returns it as stored."""
    if name not in DEFAULTS:
        raise ValueError(f"unknown setting {name!r}")
    if not get_settings().live:
        _demo_settings[(slug, name)] = on
        return on
    from app.db import pool, repo

    with pool.connection() as conn:
        repo.set_setting(conn, slug, name, on)
        conn.commit()
    return on


def reset(slugs: list[str] | tuple[str, ...], conn=None) -> None:
    """Back to the defaults for these people (the demo reset uses this)."""
    for s in slugs:
        _demo.pop(s, None)
        for name in DEFAULTS:
            _demo_settings.pop((s, name), None)
    if conn is not None and get_settings().live:
        from app.db import repo

        repo.clear_safe_floors(conn, list(slugs))

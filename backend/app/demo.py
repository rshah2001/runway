"""Demo controls: rebuild the three demo customers on demand, and hold the safety net so the live
moment happens on stage, not in the background.

Why: the demo story is "Maya is about to dip → the family safety net covers her → she pays it back".
The nightly reseed restores that story once a day, and the background safety net then covers the dip
within minutes. To rehearse — and to have a fresh story in front of the judges — a signed-in demo
login can reset the demo whenever it likes, and the reset pauses automatic bridges for a while so
the dip is still there when you show it. Running the safety net by hand ends the pause.

Only the three demo personas are ever touched. The reset runs in a background thread (it writes a
few hundred Nessie records); `status()` reports progress.
"""

import logging
import threading
from datetime import UTC, datetime, timedelta

log = logging.getLogger("runway.demo")

DEMO_PERSONAS = ("maya", "jordan", "sam")
HOLD_MINUTES = 60  # long enough to rehearse or present; the nightly reseed starts the day fresh

_lock = threading.Lock()
_status: dict = {"state": "idle", "started": None, "finished": None, "error": None}
_hold_until: datetime | None = None


def _now() -> datetime:
    return datetime.now(UTC)


# ---------- the hold ----------
def hold(minutes: int = HOLD_MINUTES) -> None:
    """Pause automatic safety-net actions (bridges, repayments, push polls) for `minutes`."""
    global _hold_until
    _hold_until = _now() + timedelta(minutes=minutes)


def release() -> None:
    """End the pause early — e.g. when someone runs the safety net by hand."""
    global _hold_until
    _hold_until = None


def held() -> bool:
    return _hold_until is not None and _now() < _hold_until


def hold_until() -> datetime | None:
    return _hold_until if held() else None


# ---------- the reset ----------
def status() -> dict:
    return {**_status, "hold_until": hold_until()}


def start_reset() -> bool:
    """Kick off a reset in the background. False if one is already running."""
    if not _lock.acquire(blocking=False):
        return False
    _status.update(state="running", started=_now(), finished=None, error=None)
    hold()  # from the first second: the background pass mustn't bridge a half-built Maya
    threading.Thread(target=_reset, name="demo-reset", daemon=True).start()
    return True


def _reset() -> None:
    try:
        rebuild()
        _status.update(state="done", finished=_now())
        hold()  # the pause counts from when the demo is ready, not from when the reset began
        log.info("demo reset done")
    except Exception as e:  # report the kind of failure, never details that could carry the key
        log.exception("demo reset failed")
        _status.update(state="failed", finished=_now(), error=type(e).__name__)
    finally:
        _lock.release()


def rebuild() -> None:
    """Rebuild the demo personas in Nessie and Tiger Data, then put the default limits back.

    Uses the seed's own reset (deletes the old accounts, reuses the customers — Nessie can't delete
    customers — and writes fresh history ending yesterday). Unlike the nightly seed, it *forces* the
    default limits, so a rehearsal where Sam lowered his limit starts over from the script.
    """
    from app.db import pool, safety_repo
    from app.db import schema as db_schema
    from app.nessie.client import NessieClient
    from seed.__main__ import ensure_merchants, seed_persona
    from seed.personas import PERSONAS, SAFETY_LIMITS

    nessie = NessieClient.from_settings()
    merchant_ids = ensure_merchants(nessie)
    for spec in PERSONAS:
        if spec.slug in DEMO_PERSONAS:
            seed_persona(nessie, spec, merchant_ids, reset=True)
    from app import prefs

    with pool.connection() as conn:
        prefs.reset(DEMO_PERSONAS, conn)  # everyone back to the default cushion
        pairs = []
        for lender, borrower, amount in SAFETY_LIMITS:
            if lender in DEMO_PERSONAS and borrower in DEMO_PERSONAS:
                safety_repo.set_limit(conn, lender, borrower, amount, True)
                pairs.append((lender, borrower))
        from app import agreements

        agreements.setup_demo(conn, pairs, force=True)  # the rehearsal starts from the script: both agreed
        conn.commit()
        db_schema.refresh_daily_spend(conn)  # after the commit, as the seed does
    from app import alerts

    alerts.reset(list(DEMO_PERSONAS))  # the dip is fresh again, so its heads-up can go out again

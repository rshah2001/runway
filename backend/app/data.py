"""Data access for the API routes: live (Nessie + Tiger Data) or built-in demo data.

Reads fall back to demo data if a live dependency is down, so the app keeps rendering during a
demo; the failure is logged and visible at /health. Money movement never falls back — a transfer
either really happens in Nessie or the request fails.
"""

import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.db import pool, repo
from app.ingest import sync_customer
from app.nessie import demo
from app.nessie.client import NessieClient, NessieError
from app.schemas import Account, CategorySpend, DailySpend, Me, Persona, Spending, SpendingTransaction

log = logging.getLogger(__name__)
LOCAL_TZ = ZoneInfo("America/New_York")
DEFAULT_PERSONA = "maya"


class PersonaNotFound(LookupError):
    pass


def mode() -> str:
    return "live" if get_settings().live else "demo"


def personas() -> list[Persona]:
    if not get_settings().live:
        return demo.PERSONAS
    try:
        with pool.connection() as conn:
            return [Persona(slug=p["slug"], first_name=p["first_name"], story=p["story"]) for p in repo.personas(conn)]
    except Exception:
        log.exception("personas: live read failed, serving demo data")
        return demo.PERSONAS


def _persona(conn, slug: str) -> dict:
    p = repo.persona(conn, slug)
    if p is None:
        raise PersonaNotFound(slug)
    return p


def me(slug: str = DEFAULT_PERSONA) -> Me:
    if not get_settings().live:
        return demo.me(slug)
    try:
        with pool.connection() as conn:
            p = _persona(conn, slug)
            accounts = [
                Account(id=a["id"], nickname=a["nickname"], type=a["type"], balance=float(a["balance"]))
                for a in repo.accounts_with_balances(conn, p["customer_id"])
            ]
            return Me(customer_id=p["customer_id"], first_name=p["first_name"], accounts=accounts)
    except PersonaNotFound:
        raise
    except Exception:
        log.exception("me: live read failed, serving demo data")
        return demo.me(slug)


def _month_bounds(month: str) -> tuple[date, date]:
    y, m = map(int, month.split("-"))
    start = date(y, m, 1)
    return start, (start + timedelta(days=32)).replace(day=1)


def spending(month: str, slug: str = DEFAULT_PERSONA) -> Spending:
    if not get_settings().live:
        return demo.spending(month)
    try:
        start, end = _month_bounds(month)
        with pool.connection() as conn:
            p = _persona(conn, slug)
            agg = repo.daily_spend(conn, p["customer_id"], start, end)  # continuous aggregate
            since = datetime.combine(start, datetime.min.time(), LOCAL_TZ)
            until = datetime.combine(end, datetime.min.time(), LOCAL_TZ)
            raw = [t for t in repo.transactions(conn, p["customer_id"], since, until) if t["kind"] == "purchase"]

        by_cat: dict[str, CategorySpend] = {}
        by_day: dict[date, float] = {}
        for row in agg:
            spent = float(row["spent"])
            c = by_cat.setdefault(row["category"], CategorySpend(category=row["category"], spent=0, purchases=0))
            c.spent = round(c.spent + spent, 2)
            c.purchases += int(row["purchases"])
            by_day[row["day"]] = round(by_day.get(row["day"], 0) + spent, 2)
        return Spending(
            month=month,
            total=round(sum(c.spent for c in by_cat.values()), 2),
            categories=sorted(by_cat.values(), key=lambda c: -c.spent),
            daily=[DailySpend(date=d, spent=s) for d, s in sorted(by_day.items())],
            transactions=[
                SpendingTransaction(
                    date=t["ts"].astimezone(LOCAL_TZ).date(),
                    merchant=t["merchant"] or t["description"] or "Unknown",
                    category=t["category"] or "Other",
                    amount=float(-t["amount"]),
                    account=t["account"],
                )
                for t in reversed(raw)
            ],
        )
    except PersonaNotFound:
        raise
    except Exception:
        log.exception("spending: live read failed, serving demo data")
        return demo.spending(month)


class TransferNotMade(RuntimeError):
    """Nothing was written to Nessie (or it was fully undone): safe to let the user retry."""


class TransferNeedsReconciliation(RuntimeError):
    """Money may have partially moved. Never retry automatically — a human must check Nessie."""


def move_savings_to_checking(amount: float, description: str, slug: str = DEFAULT_PERSONA) -> str:
    """Move money in Nessie: a transfer out of savings plus a deposit into checking (Nessie
    transfers have no destination), then re-ingest so balances update immediately.

    Real Nessie writes happen only in live mode with LIVE_TRANSFERS=1 — and that switch must stay
    off until the approve route checks the Auth0 user, or anyone could move a persona's money.
    """
    s = get_settings()
    if not (s.live and s.live_transfers):
        return demo.create_transfer("demo-sav", "demo-chk", amount, description)
    nessie = NessieClient.from_settings()
    today = datetime.now(LOCAL_TZ).date()
    with pool.connection() as conn:
        p = _persona(conn, slug)
    try:
        transfer = nessie.create_transfer(p["savings_id"], amount, today, description)
    except Exception as e:
        # a write that timed out may still have landed; only a clear rejection means nothing moved
        if isinstance(e, NessieError) and 400 <= e.status < 500:
            raise TransferNotMade(str(e)) from e
        raise TransferNeedsReconciliation(f"transfer outcome unknown: {e}") from e
    transfer_id = transfer.get("_id") or transfer.get("id", "")
    try:
        nessie.create_deposit(p["checking_id"], amount, today, f"From savings: {description}")
    except Exception as deposit_error:
        try:
            nessie.delete_transfer(transfer_id)  # undo the outgoing half
        except Exception as undo_error:
            raise TransferNeedsReconciliation(
                f"deposit failed and transfer {transfer_id} could not be undone: {undo_error}"
            ) from deposit_error
        raise TransferNotMade(f"deposit failed; transfer {transfer_id} undone: {deposit_error}") from deposit_error

    # money has moved — from here on, failures only delay the balance refresh
    try:
        with pool.connection() as conn:
            sync_customer(conn, nessie, p["customer_id"])
            conn.commit()
    except Exception:
        log.exception("transfer %s done, but re-sync failed; balances catch up on the next ingest", transfer_id)
    return transfer_id


def health() -> dict:
    status = {"ok": True, "mode": mode()}
    if get_settings().live:
        try:
            with pool.connection() as conn:
                conn.execute("SELECT 1")
            status["database"] = "ok"
        except Exception as e:
            status["database"] = f"error: {type(e).__name__}"
        from app.sync_loop import STATUS as sync_status  # imported here to keep demo mode lean

        status["sync"] = dict(sync_status)
    return status

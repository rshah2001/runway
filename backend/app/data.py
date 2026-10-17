"""Data access for the API routes: live (Nessie + Tiger Data) or built-in demo data.

Reads fall back to demo data if a live dependency is down, so the app keeps rendering during a
demo; the failure is logged and visible at /health. Money movement never falls back — a transfer
either really happens in Nessie or the request fails.
"""

import logging
import secrets
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.db import pool, repo
from app.ingest import sync_customer, ts_for
from app.nessie import demo
from app.nessie.client import NessieClient
from app.nessie.moves import TransferNeedsReconciliation, TransferNotMade, move_money
from app.schemas import (
    Account,
    CategorySpend,
    Contact,
    DailySpend,
    Me,
    P2PPayment,
    P2PRequest,
    P2PSummary,
    Persona,
    Spending,
    SpendingTransaction,
)

__all__ = ["TransferNeedsReconciliation", "TransferNotMade"]  # re-exported for the routes

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
            return [
                Persona(slug=p["slug"], first_name=p["first_name"], age=p["age"] or 0, story=p["story"])
                for p in repo.personas(conn)
            ]
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


def _writes_enabled() -> bool:
    """Real Nessie writes need live mode AND LIVE_TRANSFERS=1 — keep the switch off until the
    routes check the Auth0 user, or anyone could move a persona's money."""
    s = get_settings()
    return s.live and s.live_transfers


def _resync(nessie: NessieClient, customer_id: str) -> None:
    # money has moved — from here on, failures only delay the balance refresh
    try:
        with pool.connection() as conn:
            sync_customer(conn, nessie, customer_id)
            conn.commit()
    except Exception:
        log.exception("money moved, but re-sync failed; balances catch up on the next background sync")


def move_savings_to_checking(amount: float, description: str, slug: str = DEFAULT_PERSONA) -> str:
    """ "Fix it": really move money from the persona's savings into checking."""
    if not _writes_enabled():
        return demo.create_transfer("demo-sav", "demo-chk", amount, description)
    nessie = NessieClient.from_settings()
    with pool.connection() as conn:
        p = _persona(conn, slug)
    today = datetime.now(LOCAL_TZ).date()
    transfer_id, _ = move_money(
        nessie, p["savings_id"], p["checking_id"], amount, today, description, f"From savings: {description}"
    )
    _resync(nessie, p["customer_id"])
    return transfer_id


# ---------- peer-to-peer ----------
class ContactNotFound(LookupError):
    pass


class RequestNotOpen(LookupError):
    pass


def _payment(row: dict) -> P2PPayment:
    return P2PPayment(
        id=row["id"],
        date=row["ts"].astimezone(LOCAL_TZ).date(),
        direction=row["direction"],
        contact_id=row["contact_id"],
        contact=row["contact_name"],
        amount=float(row["amount"]),
        memo=row["memo"],
    )


def _request(row: dict) -> P2PRequest:
    return P2PRequest(
        id=row["id"],
        contact_id=row["contact_id"],
        contact=row["contact_name"],
        amount=float(row["amount"]),
        memo=row["memo"],
        status=row["status"],
        created=row["created_at"].astimezone(LOCAL_TZ).date(),
    )


def p2p_summary(slug: str = DEFAULT_PERSONA) -> P2PSummary:
    if not get_settings().live:
        return demo.p2p_summary(slug)
    try:
        with pool.connection() as conn:
            _persona(conn, slug)
            requests = [_request(r) for r in repo.requests(conn, slug)]
            owed: dict[str, float] = {}
            for r in requests:
                if r.status == "open":
                    owed[r.contact_id] = round(owed.get(r.contact_id, 0) + r.amount, 2)
            return P2PSummary(
                contacts=[
                    Contact(id=c["id"], name=c["first_name"], relation=c["relation"], owes_you=owed.get(c["id"], 0))
                    for c in repo.contacts(conn, slug)
                ],
                payments=[_payment(p) for p in repo.p2p_payments(conn, slug)],
                requests=requests,
            )
    except PersonaNotFound:
        raise
    except Exception:
        log.exception("p2p: live read failed, serving demo data")
        return demo.p2p_summary(slug)


def _contact_for(conn, slug: str, contact_id: str) -> dict:
    c = repo.contact(conn, contact_id)
    if c is None or c["persona_slug"] != slug:  # a persona can only pay its own contacts
        raise ContactNotFound(contact_id)
    return c


def _record_payment(nessie: NessieClient, p: dict, c: dict, direction: str, amount: float, memo: str) -> dict:
    """Move the money in Nessie (both sides) and record it. `direction` is from the persona's view."""
    today = datetime.now(LOCAL_TZ).date()
    if direction == "out":
        sender, receiver = p["checking_id"], c["checking_id"]
        deposit_memo = f"From {p['first_name']}: {memo}"
    else:
        sender, receiver = c["checking_id"], p["checking_id"]
        deposit_memo = f"From {c['first_name']}: {memo}"
    transfer_id, deposit_id = move_money(nessie, sender, receiver, amount, today, memo, deposit_memo)
    row = {
        "id": f"p2p-{secrets.token_hex(8)}",
        "persona_slug": p["slug"],
        "contact_id": c["id"],
        "direction": direction,
        "amount": round(amount, 2),
        "memo": memo,
        "ts": ts_for(today),
        "sender_nessie_id": transfer_id,
        "receiver_nessie_id": deposit_id,
    }
    with pool.connection() as conn:
        repo.insert_p2p_payment(conn, row)
        conn.commit()
    _resync(nessie, p["customer_id"])
    return {**row, "contact_name": c["first_name"]}


def p2p_send(slug: str, contact_id: str, amount: float, memo: str) -> P2PPayment:
    """The persona pays a contact."""
    if not _writes_enabled():
        return demo.p2p_payment(contact_id, "out", amount, memo)
    with pool.connection() as conn:
        p, c = _persona(conn, slug), _contact_for(conn, slug, contact_id)
    return _payment(_record_payment(NessieClient.from_settings(), p, c, "out", amount, memo))


def p2p_request(slug: str, contact_id: str, amount: float, memo: str) -> P2PRequest:
    """Ask a contact for money. No money moves until the request is settled."""
    if not _writes_enabled():
        return demo.p2p_request(contact_id, amount, memo)
    with pool.connection() as conn:
        _persona(conn, slug)
        c = _contact_for(conn, slug, contact_id)
        row = {
            "id": f"req-{secrets.token_hex(8)}",
            "persona_slug": slug,
            "contact_id": c["id"],
            "amount": round(amount, 2),
            "memo": memo,
            "created_at": datetime.now(LOCAL_TZ),
        }
        repo.insert_request(conn, row)
        conn.commit()
    return _request({**row, "status": "open", "contact_name": c["first_name"]})


def p2p_settle(request_id: str) -> P2PRequest:
    """The contact pays an open request: real money from their account into the persona's."""
    if not _writes_enabled():
        demo_req = next((r for r in demo.p2p_summary().requests if r.id == request_id), None)
        if demo_req is None:
            raise RequestNotOpen(request_id)
        return demo_req.model_copy(update={"status": "paid"})
    with pool.connection() as conn:
        claimed = repo.claim_request(conn, request_id)  # atomic open → settling
        conn.commit()
        if claimed is None:
            raise RequestNotOpen(request_id)
        p = _persona(conn, claimed["persona_slug"])
        c = repo.contact(conn, claimed["contact_id"])
    try:
        payment = _record_payment(NessieClient.from_settings(), p, c, "in", float(claimed["amount"]), claimed["memo"])
    except TransferNotMade:
        with pool.connection() as conn:
            repo.finish_request(conn, request_id, "open")  # nothing moved: can be settled again
            conn.commit()
        raise
    except Exception:
        with pool.connection() as conn:
            repo.finish_request(conn, request_id, "failed")  # outcome unknown: never settle twice
            conn.commit()
        raise
    with pool.connection() as conn:
        row = repo.finish_request(conn, request_id, "paid", payment["id"])
        conn.commit()
    return _request(row)


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

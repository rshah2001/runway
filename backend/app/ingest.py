"""Nessie → Tiger Data sync. Idempotent: every row is upserted by its Nessie id.

Run:  python -m app.ingest            (all seeded personas)
      python -m app.ingest maya sam   (just these)
"""

import logging
import sys
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import psycopg

from app.db import pool, repo
from app.db import schema as db_schema
from app.nessie.client import NessieClient, from_cents

log = logging.getLogger(__name__)
LOCAL_TZ = ZoneInfo("America/New_York")


def ts_for(day: str | date) -> datetime:
    """Nessie stores dates only; pin each to local noon so it lands on the right calendar day."""
    d = date.fromisoformat(day) if isinstance(day, str) else day
    return datetime.combine(d, time(12), LOCAL_TZ)


def start_of_day(d: date) -> datetime:
    return datetime.combine(d, time(0), LOCAL_TZ)


def _nid(obj: dict) -> str:
    return obj.get("_id") or obj["id"]  # Nessie's transfer list uses "id", everything else "_id"


def sync_customer(
    conn: psycopg.Connection, nessie: NessieClient, customer_id: str, opening_at: datetime | None = None
) -> dict:
    """Pull one customer's accounts, transactions and bills from Nessie into Tiger Data.

    `opening_at` only applies to accounts seen for the first time: their current Nessie balance
    becomes the opening balance as of that moment (default: now).
    """
    merchants = repo.merchants(conn)
    for m in nessie.merchants():
        if _nid(m) not in merchants:
            row = {"id": _nid(m), "name": m["name"], "category": m.get("category") or "Other"}
            repo.upsert_merchant(conn, row)
            merchants[row["id"]] = row

    counts = {"accounts": 0, "transactions": 0, "bills": 0}
    for acct in nessie.accounts(customer_id):
        aid = _nid(acct)
        repo.upsert_account(
            conn,
            {
                "id": aid,
                "customer_id": customer_id,
                "type": acct["type"],
                "nickname": acct["nickname"],
                "opening_balance": from_cents(acct["balance"]),
                "opening_at": opening_at or datetime.now(LOCAL_TZ),
            },
        )
        counts["accounts"] += 1

        rows = []
        base = {"account_id": aid, "customer_id": customer_id, "merchant_id": None, "category": None}
        for p in nessie.purchases(aid):
            m = merchants.get(p.get("merchant_id"), {})
            rows.append(
                {
                    **base,
                    "ts": ts_for(p["purchase_date"]),
                    "nessie_id": _nid(p),
                    "kind": "purchase",
                    "amount": -from_cents(p["amount"]),
                    "merchant_id": p.get("merchant_id"),
                    "category": m.get("category", "Other"),
                    "description": p.get("description"),
                    "status": p.get("status", "completed"),
                }
            )
        for kind, items, date_key, sign in (
            ("deposit", nessie.deposits(aid), "transaction_date", 1),
            ("withdrawal", nessie.withdrawals(aid), "transaction_date", -1),
            ("transfer", nessie.transfers(aid), "transaction_date", -1),  # always outgoing — Nessie has no payee
        ):
            for t in items:
                rows.append(
                    {
                        **base,
                        "ts": ts_for(t[date_key]),
                        "nessie_id": _nid(t),
                        "kind": kind,
                        "amount": sign * from_cents(t["amount"]),
                        "description": t.get("description"),
                        "status": t.get("status", "completed"),
                    }
                )
        for b in nessie.bills(aid):
            if b["status"] == "completed":
                rows.append(
                    {
                        **base,
                        "ts": ts_for(b["payment_date"]),
                        "nessie_id": _nid(b),
                        "kind": "bill",
                        "amount": -from_cents(b["payment_amount"]),
                        "category": "Bills",
                        "description": b.get("nickname") or b["payee"],
                        "status": "completed",
                    }
                )
            else:
                repo.upsert_bill(
                    conn,
                    {
                        "id": _nid(b),
                        "account_id": aid,
                        "customer_id": customer_id,
                        "payee": b["payee"],
                        "nickname": b.get("nickname") or b["payee"],
                        "amount": from_cents(b["payment_amount"]),
                        "recurring_day": b.get("recurring_date"),
                        "status": b["status"],
                        "next_payment_date": b.get("upcoming_payment_date") or b.get("payment_date"),
                    },
                )
                counts["bills"] += 1
        counts["transactions"] += repo.upsert_transactions(conn, rows)
    return counts


def sync_personas(slugs: list[str] | None = None, *, prepare: bool = True) -> None:
    """Sync personas. `prepare=False` (the background loop) skips the schema check and the
    aggregate refresh: startup already applied the schema, and daily_spend is real-time."""
    nessie = NessieClient.from_settings()
    with pool.connection() as conn:
        if prepare:
            db_schema.apply(conn)
        targets = [p for p in repo.personas(conn) if not slugs or p["slug"] in slugs]
        for p in targets:
            counts = sync_customer(conn, nessie, p["customer_id"])
            conn.commit()
            log.info("synced %s: %s", p["slug"], counts)
        if prepare:
            db_schema.refresh_daily_spend(conn)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sync_personas(sys.argv[1:] or None)

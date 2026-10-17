"""Seed the demo personas into Nessie, then ingest them into Tiger Data.

    python -m seed                 # create any persona that doesn't exist yet (never duplicates)
    python -m seed --reset maya    # wipe Maya's accounts + history and rebuild them for today

Nessie can't delete purchases, customers or merchants, so the seed is careful: personas and their
Nessie ids are recorded in Tiger Data (`personas` table) and an existing persona is never re-created.
A reset deletes the persona's accounts (which removes their purchases) and reuses the customer.
"""

import argparse
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo

from app.db import pool, repo
from app.db import schema as db_schema
from app.ingest import start_of_day, sync_customer
from app.nessie.client import NessieClient
from seed.personas import MERCHANTS, PERSONAS, PersonaSpec
from seed.plan import Op, build_plan

log = logging.getLogger("seed")
ADDRESS = {
    "street_number": "100",
    "street_name": "University Ave",
    "city": "Gainesville",
    "state": "FL",
    "zip": "32601",
}
WORKERS = 8  # Nessie answers in ~0.3 s; a few parallel writes keep a full seed under a minute


def ensure_merchants(nessie: NessieClient) -> dict[str, str]:
    """Merchant name → Nessie id, creating the ones that don't exist yet (merchants can't be deleted)."""
    existing = {m["name"]: m["_id"] for m in nessie.merchants()}
    for name, (category, street, lat, lng) in MERCHANTS.items():
        if name not in existing:
            addr = {**ADDRESS, "street_number": "1", "street_name": street}
            existing[name] = nessie.create_merchant(name, category, addr, lat, lng)["_id"]
            log.info("created merchant %s", name)
    return existing


def execute(nessie: NessieClient, op: Op, accounts: dict[str, str], merchant_ids: dict[str, str]) -> None:
    aid = accounts[op.account]
    if op.kind == "purchase":
        nessie.create_purchase(aid, merchant_ids[op.merchant], op.amount, op.on, op.description)
    elif op.kind == "deposit":
        nessie.create_deposit(aid, op.amount, op.on, op.description)
    else:
        nessie.create_bill(
            aid, op.payee, op.description, op.amount, status=op.bill_status, payment_date=op.on, day=op.day
        )


def seed_persona(nessie: NessieClient, spec: PersonaSpec, merchant_ids: dict[str, str], reset: bool) -> None:
    today = datetime.now(ZoneInfo("America/New_York")).date()
    with pool.connection() as conn:
        existing = repo.persona(conn, spec.slug)
        if existing and not reset:
            log.info(
                "%s already seeded on %s — skipping (use --reset %s to rebuild)",
                spec.slug,
                existing["seeded_at"],
                spec.slug,
            )
            return
        if existing:
            for key in ("checking_id", "savings_id", "credit_id"):
                nessie.delete_account(existing[key])
            repo.forget_customer(conn, existing["customer_id"])
            conn.commit()
            customer_id = existing["customer_id"]
            log.info("%s: deleted old accounts, reusing customer %s", spec.slug, customer_id)
        else:
            customer_id = nessie.create_customer(spec.first_name, spec.last_name, ADDRESS)["_id"]

        accounts = {
            "checking": nessie.create_account(customer_id, "Checking", "Everyday Checking", spec.checking)["_id"],
            "savings": nessie.create_account(customer_id, "Savings", "Savings", spec.savings)["_id"],
            "credit": nessie.create_account(customer_id, "Credit Card", "Rewards credit card", spec.credit_owed)["_id"],
        }
        # record the ids before writing history: if Nessie fails halfway, a rerun with --reset
        # cleans up these accounts instead of orphaning an undeletable customer
        repo.save_persona(
            conn,
            {
                "slug": spec.slug,
                "first_name": spec.first_name,
                "story": spec.story,
                "customer_id": customer_id,
                "checking_id": accounts["checking"],
                "savings_id": accounts["savings"],
                "credit_id": accounts["credit"],
            },
        )
        conn.commit()

        plan = build_plan(spec, today)
        log.info("%s: writing %d records to Nessie…", spec.slug, len(plan))
        with ThreadPoolExecutor(WORKERS) as ex:
            list(ex.map(lambda op: execute(nessie, op, accounts, merchant_ids), plan))

        # today's balances are the opening balances; all seeded history is before today, so it
        # explains the balance without changing it
        counts = sync_customer(conn, nessie, customer_id, opening_at=start_of_day(today))
        conn.commit()
        log.info("%s: ingested %s", spec.slug, counts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reset", nargs="*", default=[], metavar="SLUG", help="rebuild these personas from scratch")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    nessie = NessieClient.from_settings()
    with pool.connection() as conn:
        db_schema.apply(conn)
    merchant_ids = ensure_merchants(nessie)
    for spec in PERSONAS:
        seed_persona(nessie, spec, merchant_ids, reset=spec.slug in args.reset)
    with pool.connection() as conn:
        db_schema.refresh_daily_spend(conn)
    log.info("done — %s", ", ".join(p.slug for p in PERSONAS))
    pool.close()


if __name__ == "__main__":
    main()

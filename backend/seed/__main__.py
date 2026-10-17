"""Seed the demo personas into Nessie, then ingest them into Tiger Data.

    python -m seed                 # create any persona that doesn't exist yet (never duplicates)
    python -m seed --reset maya    # wipe Maya's accounts + history and rebuild them for today

Nessie can't delete purchases, customers or merchants, so the seed is careful: personas, their
contacts and all Nessie ids are recorded in Tiger Data and an existing persona is never re-created.
A reset deletes the persona's and its contacts' accounts (which removes their history) and reuses
the customers.
"""

import argparse
import logging
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app import agreements
from app.db import pool, repo, safety_repo
from app.db import schema as db_schema
from app.ingest import start_of_day, sync_customer, ts_for
from app.nessie.client import NessieClient
from app.nessie.moves import move_money
from seed.personas import MERCHANTS, PERSONAS, SAFETY_LIMITS, PersonaSpec
from seed.plan import Op, build_plan, demo_opening_balance

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


CONTACT_OPENING_BALANCE = 500.00


def ensure_contacts(nessie: NessieClient, conn, spec: PersonaSpec) -> dict[str, dict]:
    """Contact key → contacts row. Each contact is a Nessie customer (created once, reused forever —
    customers can't be deleted) with a fresh checking account for this seed."""
    existing = {c["id"]: c for c in repo.contacts(conn, spec.slug)}
    out = {}
    for c in spec.contacts:
        cid = f"{spec.slug}-{c.key}"
        customer_id = existing[cid]["customer_id"] if cid in existing else None
        if customer_id is None:
            customer_id = nessie.create_customer(c.first_name, c.last_name, ADDRESS)["_id"]
        checking_id = nessie.create_account(
            customer_id, "Checking", f"{c.first_name}'s Checking", CONTACT_OPENING_BALANCE
        )["_id"]
        row = {
            "id": cid,
            "persona_slug": spec.slug,
            "first_name": c.first_name,
            "last_name": c.last_name,
            "relation": c.relation,
            "customer_id": customer_id,
            "checking_id": checking_id,
        }
        repo.upsert_contact(conn, row)
        out[c.key] = row
    return out


def execute(
    nessie: NessieClient,
    op: Op,
    accounts: dict[str, str],
    merchant_ids: dict[str, str],
    contacts: dict[str, dict],
    spec: PersonaSpec,
) -> dict | None:
    """Write one planned record to Nessie. Peer-to-peer ops return the p2p_payments row to store."""
    aid = accounts[op.account]
    if op.kind == "p2p":
        c = contacts[op.contact]
        if op.direction == "out":
            sender, receiver, payer = aid, c["checking_id"], spec.first_name
        else:
            sender, receiver, payer = c["checking_id"], aid, c["first_name"]
        transfer_id, deposit_id = move_money(
            nessie, sender, receiver, op.amount, op.on, op.description, f"From {payer}: {op.description}"
        )
        return {
            "id": f"p2p-{secrets.token_hex(8)}",
            "persona_slug": spec.slug,
            "contact_id": c["id"],
            "direction": op.direction,
            "amount": op.amount,
            "memo": op.description,
            "ts": ts_for(op.on),
            "sender_nessie_id": transfer_id,
            "receiver_nessie_id": deposit_id,
        }
    if op.kind == "purchase":
        nessie.create_purchase(aid, merchant_ids[op.merchant], op.amount, op.on, op.description)
    elif op.kind == "deposit":
        nessie.create_deposit(aid, op.amount, op.on, op.description)
    else:
        nessie.create_bill(
            aid, op.payee, op.description, op.amount, status=op.bill_status, payment_date=op.on, day=op.day
        )
    return None


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
        if existing and safety_repo.unsettled(conn, spec.slug):
            # a transfer involving this persona is mid-flight or being reconciled: deleting its accounts
            # would make Nessie answer "no such transfer" and hide what really happened
            log.warning("%s has an unsettled transfer — not resetting it this time", spec.slug)
            return
        if existing:
            for key in ("checking_id", "savings_id", "credit_id"):
                nessie.delete_account(existing[key])
            for c in repo.contacts(conn, spec.slug):
                nessie.delete_account(c["checking_id"])  # the contact's side of the old P2P history
            repo.forget_p2p(conn, spec.slug)
            safety_repo.forget(conn, spec.slug)  # bridges point at the accounts being deleted
            repo.forget_customer(conn, existing["customer_id"])
            conn.commit()
            customer_id = existing["customer_id"]
            log.info("%s: deleted old accounts, reusing customer %s", spec.slug, customer_id)
        else:
            customer_id = nessie.create_customer(spec.first_name, spec.last_name, ADDRESS)["_id"]

        plan = build_plan(spec, today)
        checking = demo_opening_balance(spec, plan, today) if spec.demo_low_before_payday else spec.checking
        accounts = {
            "checking": nessie.create_account(customer_id, "Checking", "Everyday Checking", checking)["_id"],
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
                "age": spec.age,
                "story": spec.story,
                "customer_id": customer_id,
                "checking_id": accounts["checking"],
                "savings_id": accounts["savings"],
                "credit_id": accounts["credit"],
            },
        )
        contacts = ensure_contacts(nessie, conn, spec)
        conn.commit()

        log.info("%s: writing %d records to Nessie…", spec.slug, len(plan))
        with ThreadPoolExecutor(WORKERS) as ex:
            results = list(ex.map(lambda op: execute(nessie, op, accounts, merchant_ids, contacts, spec), plan))
        for payment in filter(None, results):
            repo.insert_p2p_payment(conn, payment)
        for r in spec.requests:  # open IOUs: app-level (Nessie has no requests); settled with a real P2P move
            repo.insert_request(
                conn,
                {
                    "id": f"req-{secrets.token_hex(8)}",
                    "persona_slug": spec.slug,
                    "contact_id": contacts[r.contact]["id"],
                    "amount": r.amount,
                    "memo": r.memo,
                    "created_at": ts_for(today - timedelta(days=r.days_ago)),
                },
            )

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
        for lender, borrower, amount in SAFETY_LIMITS:  # defaults; a lender's own change is never overwritten
            safety_repo.seed_limit(conn, lender, borrower, amount)
        # the scripted relationships get both consents through an auditable setup step; a pair either
        # person has acted on (agreed or revoked) is left exactly as they left it
        agreements.setup_demo(conn, [(lender, borrower) for lender, borrower, _ in SAFETY_LIMITS])
        conn.commit()
        db_schema.refresh_daily_spend(conn)
    log.info("done — %s", ", ".join(p.slug for p in PERSONAS))
    pool.close()


if __name__ == "__main__":
    main()

"""Read/write queries against Tiger Data.

The read functions are the data interface for the forecast engine and the agent
(backend/app/forecast, backend/app/agent): they return plain dicts with Decimal amounts, already
scoped to one customer, so callers never write SQL.
"""

from datetime import date, datetime
from typing import Any

import psycopg

Row = dict[str, Any]


# ---------- personas ----------
def personas(conn: psycopg.Connection) -> list[Row]:
    return conn.execute("SELECT * FROM personas ORDER BY seeded_at, slug").fetchall()


def persona(conn: psycopg.Connection, slug: str) -> Row | None:
    return conn.execute("SELECT * FROM personas WHERE slug = %s", (slug,)).fetchone()


def save_persona(conn: psycopg.Connection, p: Row) -> None:
    conn.execute(
        """INSERT INTO personas (slug, first_name, story, customer_id, checking_id, savings_id, credit_id)
           VALUES (%(slug)s, %(first_name)s, %(story)s, %(customer_id)s, %(checking_id)s, %(savings_id)s, %(credit_id)s)
           ON CONFLICT (slug) DO UPDATE SET
             first_name = EXCLUDED.first_name, story = EXCLUDED.story, customer_id = EXCLUDED.customer_id,
             checking_id = EXCLUDED.checking_id, savings_id = EXCLUDED.savings_id,
             credit_id = EXCLUDED.credit_id, seeded_at = now()""",
        p,
    )


def forget_customer(conn: psycopg.Connection, customer_id: str) -> None:
    """Drop everything cached for a customer (used when re-seeding)."""
    for table in ("transactions", "bills", "accounts"):
        conn.execute(f"DELETE FROM {table} WHERE customer_id = %s", (customer_id,))


# ---------- writes used by ingest ----------
def upsert_account(conn: psycopg.Connection, a: Row) -> None:
    conn.execute(
        """INSERT INTO accounts (id, customer_id, type, nickname, opening_balance, opening_at)
           VALUES (%(id)s, %(customer_id)s, %(type)s, %(nickname)s, %(opening_balance)s, %(opening_at)s)
           ON CONFLICT (id) DO UPDATE SET nickname = EXCLUDED.nickname""",  # opening values never move
        a,
    )


def upsert_merchant(conn: psycopg.Connection, m: Row) -> None:
    conn.execute(
        """INSERT INTO merchants (id, name, category) VALUES (%(id)s, %(name)s, %(category)s)
           ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, category = EXCLUDED.category""",
        m,
    )


def merchants(conn: psycopg.Connection) -> dict[str, Row]:
    return {r["id"]: r for r in conn.execute("SELECT * FROM merchants").fetchall()}


def upsert_bill(conn: psycopg.Connection, b: Row) -> None:
    conn.execute(
        """INSERT INTO bills (id, account_id, customer_id, payee, nickname, amount, recurring_day, status,
                              next_payment_date)
           VALUES (%(id)s, %(account_id)s, %(customer_id)s, %(payee)s, %(nickname)s, %(amount)s,
                   %(recurring_day)s, %(status)s, %(next_payment_date)s)
           ON CONFLICT (id) DO UPDATE SET amount = EXCLUDED.amount, status = EXCLUDED.status,
             recurring_day = EXCLUDED.recurring_day, next_payment_date = EXCLUDED.next_payment_date""",
        b,
    )


def upsert_transactions(conn: psycopg.Connection, rows: list[Row]) -> int:
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO transactions (ts, nessie_id, account_id, customer_id, kind, amount, merchant_id,
                                         category, description, status)
               VALUES (%(ts)s, %(nessie_id)s, %(account_id)s, %(customer_id)s, %(kind)s, %(amount)s,
                       %(merchant_id)s, %(category)s, %(description)s, %(status)s)
               ON CONFLICT (nessie_id, ts) DO UPDATE SET
                 amount = EXCLUDED.amount, status = EXCLUDED.status, category = EXCLUDED.category,
                 description = EXCLUDED.description""",
            rows,
        )
    return len(rows)


# ---------- reads (forecast / agent / API) ----------
def accounts_with_balances(conn: psycopg.Connection, customer_id: str) -> list[Row]:
    """Live balance per account. Credit Card balance = amount owed (purchases increase it)."""
    return conn.execute(
        """SELECT a.id, a.type, a.nickname,
                  a.opening_balance + CASE WHEN a.type = 'Credit Card' THEN -1 ELSE 1 END
                      * COALESCE(sum(t.amount) FILTER (WHERE t.status = 'completed'), 0) AS balance
           FROM accounts a
           LEFT JOIN transactions t ON t.account_id = a.id AND t.ts >= a.opening_at
           WHERE a.customer_id = %s
           GROUP BY a.id
           ORDER BY array_position(ARRAY['Checking', 'Savings', 'Credit Card'], a.type)""",
        (customer_id,),
    ).fetchall()


def transactions(
    conn: psycopg.Connection, customer_id: str, since: datetime, until: datetime | None = None
) -> list[Row]:
    """Raw history, oldest first, with merchant names joined in."""
    return conn.execute(
        """SELECT t.ts, t.kind, t.amount, t.category, t.description, t.status, t.account_id,
                  a.type AS account_type, a.nickname AS account, m.name AS merchant
           FROM transactions t
           JOIN accounts a ON a.id = t.account_id
           LEFT JOIN merchants m ON m.id = t.merchant_id
           WHERE t.customer_id = %s AND t.ts >= %s AND t.ts < COALESCE(%s, 'infinity'::timestamptz)
           ORDER BY t.ts""",
        (customer_id, since, until),
    ).fetchall()


def bills(conn: psycopg.Connection, customer_id: str) -> list[Row]:
    """Upcoming recurring bills (the forecast's scheduled outflows)."""
    return conn.execute(
        """SELECT b.*, a.type AS account_type FROM bills b JOIN accounts a ON a.id = b.account_id
           WHERE b.customer_id = %s AND b.status = 'recurring' ORDER BY b.recurring_day""",
        (customer_id,),
    ).fetchall()


def daily_spend(conn: psycopg.Connection, customer_id: str, start: date, end: date) -> list[Row]:
    """Per-day, per-category spend from the continuous aggregate, for [start, end)."""
    return conn.execute(
        """SELECT day::date AS day, category, spent, purchases FROM daily_spend
           WHERE customer_id = %s AND day >= %s AND day < %s ORDER BY day, category""",
        (customer_id, start, end),
    ).fetchall()

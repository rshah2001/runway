"""Read/write queries against Tiger Data.

The read functions are the data interface for the forecast engine and the agent
(backend/app/forecast, backend/app/agent): they return plain dicts with Decimal amounts, already
scoped to one customer, so callers never write SQL.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

import psycopg
from psycopg import sql

Row = dict[str, Any]


# ---------- personas ----------
def personas(conn: psycopg.Connection) -> list[Row]:
    return conn.execute("SELECT * FROM personas ORDER BY seeded_at, slug").fetchall()


def persona(conn: psycopg.Connection, slug: str) -> Row | None:
    return conn.execute("SELECT * FROM personas WHERE slug = %s", (slug,)).fetchone()


def save_persona(conn: psycopg.Connection, p: Row) -> None:
    conn.execute(
        """INSERT INTO personas (slug, first_name, age, story, customer_id, checking_id, savings_id, credit_id)
           VALUES (%(slug)s, %(first_name)s, %(age)s, %(story)s, %(customer_id)s, %(checking_id)s, %(savings_id)s,
                   %(credit_id)s)
           ON CONFLICT (slug) DO UPDATE SET
             first_name = EXCLUDED.first_name, age = EXCLUDED.age, story = EXCLUDED.story,
             customer_id = EXCLUDED.customer_id,
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


# ---------- peer-to-peer ----------
def contacts(conn: psycopg.Connection, slug: str) -> list[Row]:
    return conn.execute("SELECT * FROM contacts WHERE persona_slug = %s ORDER BY id", (slug,)).fetchall()


def contact(conn: psycopg.Connection, contact_id: str) -> Row | None:
    return conn.execute("SELECT * FROM contacts WHERE id = %s", (contact_id,)).fetchone()


def upsert_contact(conn: psycopg.Connection, c: Row) -> None:
    conn.execute(
        """INSERT INTO contacts (id, persona_slug, first_name, last_name, relation, customer_id, checking_id)
           VALUES (%(id)s, %(persona_slug)s, %(first_name)s, %(last_name)s, %(relation)s, %(customer_id)s,
                   %(checking_id)s)
           ON CONFLICT (id) DO UPDATE SET first_name = EXCLUDED.first_name, last_name = EXCLUDED.last_name,
             relation = EXCLUDED.relation, checking_id = EXCLUDED.checking_id""",
        c,
    )


def forget_p2p(conn: psycopg.Connection, slug: str) -> None:
    """Drop a persona's payments and requests (contacts are kept: their Nessie customers can't be deleted)."""
    conn.execute("DELETE FROM p2p_requests WHERE persona_slug = %s", (slug,))
    conn.execute("DELETE FROM p2p_payments WHERE persona_slug = %s", (slug,))


def insert_p2p_payment(conn: psycopg.Connection, p: Row) -> None:
    conn.execute(
        """INSERT INTO p2p_payments (id, persona_slug, contact_id, direction, amount, memo, ts, sender_nessie_id,
                                     receiver_nessie_id)
           VALUES (%(id)s, %(persona_slug)s, %(contact_id)s, %(direction)s, %(amount)s, %(memo)s, %(ts)s,
                   %(sender_nessie_id)s, %(receiver_nessie_id)s)
           ON CONFLICT (id) DO NOTHING""",
        p,
    )


def paycheck_landed(conn: psycopg.Connection, account_id: str, since: date, at_least: Decimal) -> bool:
    """A real income deposit of at least `at_least` landed on `account_id` on or after `since` — not a
    Runway move (tagged [rw:…]) and not safety-net money, so a bridge can never "repay itself"."""
    row = conn.execute(
        """SELECT 1 FROM transactions
           WHERE account_id = %s AND kind = 'deposit' AND status = 'completed' AND amount >= %s AND ts >= %s
             AND COALESCE(description, '') NOT LIKE '%%[rw:%%'
             AND COALESCE(description, '') NOT ILIKE '%%safety net%%'
           LIMIT 1""",
        (account_id, at_least, since),
    ).fetchone()
    return row is not None


def p2p_payment(conn: psycopg.Connection, payment_id: str) -> Row | None:
    return conn.execute(
        """SELECT p.*, c.first_name AS contact_name FROM p2p_payments p JOIN contacts c ON c.id = p.contact_id
           WHERE p.id = %s""",
        (payment_id,),
    ).fetchone()


def p2p_payments(conn: psycopg.Connection, slug: str, limit: int = 50) -> list[Row]:
    return conn.execute(
        """SELECT p.*, c.first_name AS contact_name FROM p2p_payments p JOIN contacts c ON c.id = p.contact_id
           WHERE p.persona_slug = %s ORDER BY p.ts DESC, p.id LIMIT %s""",
        (slug, limit),
    ).fetchall()


def insert_request(conn: psycopg.Connection, r: Row) -> None:
    conn.execute(
        """INSERT INTO p2p_requests (id, persona_slug, contact_id, amount, memo, status, created_at)
           VALUES (%(id)s, %(persona_slug)s, %(contact_id)s, %(amount)s, %(memo)s, 'open', %(created_at)s)""",
        r,
    )


def requests(conn: psycopg.Connection, slug: str) -> list[Row]:
    return conn.execute(
        """SELECT r.*, c.first_name AS contact_name FROM p2p_requests r JOIN contacts c ON c.id = r.contact_id
           WHERE r.persona_slug = %s
           ORDER BY (r.status = 'open') DESC, r.created_at DESC""",
        (slug,),
    ).fetchall()


def claim_request(conn: psycopg.Connection, request_id: str) -> Row | None:
    """Atomically move an open request to 'settling'. Returns None if it wasn't open — so two
    simultaneous settles can never both move money."""
    return conn.execute(
        "UPDATE p2p_requests SET status = 'settling' WHERE id = %s AND status = 'open' RETURNING *", (request_id,)
    ).fetchone()


def finish_request(conn: psycopg.Connection, request_id: str, status: str, payment_id: str | None = None) -> Row:
    return conn.execute(
        """UPDATE p2p_requests SET status = %s, payment_id = %s,
             settled_at = CASE WHEN %s = 'paid' THEN now() ELSE settled_at END
           WHERE id = %s
           RETURNING *, (SELECT first_name FROM contacts WHERE id = contact_id) AS contact_name""",
        (status, payment_id, status, request_id),
    ).fetchone()


# ---------- money preferences ----------
def safe_floor(conn: psycopg.Connection, slug: str) -> float | None:
    """The amount this person keeps in checking, or None if they never set one."""
    row = conn.execute("SELECT safe_floor FROM money_preferences WHERE slug = %s", (slug,)).fetchone()
    # a row can exist with only on/off settings saved: a NULL floor means "never set it" too
    return float(row["safe_floor"]) if row and row["safe_floor"] is not None else None


def set_safe_floor(conn: psycopg.Connection, slug: str, amount: float) -> None:
    conn.execute(
        """INSERT INTO money_preferences (slug, safe_floor) VALUES (%s, %s)
           ON CONFLICT (slug) DO UPDATE SET safe_floor = EXCLUDED.safe_floor, updated_at = now()""",
        (slug, amount),
    )


def exposure_limit(conn: psycopg.Connection, slug: str) -> float | None:
    """The most this person lets Runway have out across everyone they support, or None (the default)."""
    row = conn.execute("SELECT support_exposure_limit FROM money_preferences WHERE slug = %s", (slug,)).fetchone()
    return float(row["support_exposure_limit"]) if row and row["support_exposure_limit"] is not None else None


def set_exposure_limit(conn: psycopg.Connection, slug: str, amount: float) -> None:
    conn.execute(
        """INSERT INTO money_preferences (slug, support_exposure_limit) VALUES (%s, %s)
           ON CONFLICT (slug) DO UPDATE
             SET support_exposure_limit = EXCLUDED.support_exposure_limit, updated_at = now()""",
        (slug, amount),
    )


def clear_safe_floors(conn: psycopg.Connection, slugs: list[str]) -> None:
    """Back to every default (floor and on/off settings) for these people."""
    conn.execute("DELETE FROM money_preferences WHERE slug = ANY(%s)", (slugs,))


SETTINGS = ("alerts_only", "family_cover")  # on/off columns of money_preferences


def setting(conn: psycopg.Connection, slug: str, name: str) -> bool | None:
    """One on/off setting, or None if this person never changed it."""
    col = _setting_column(name)
    q = sql.SQL("SELECT {} AS v FROM money_preferences WHERE slug = %s").format(col)
    row = conn.execute(q, (slug,)).fetchone()
    return row["v"] if row else None


def set_setting(conn: psycopg.Connection, slug: str, name: str, on: bool) -> None:
    col = _setting_column(name)
    q = sql.SQL(
        "INSERT INTO money_preferences (slug, {c}) VALUES (%s, %s) "
        "ON CONFLICT (slug) DO UPDATE SET {c} = EXCLUDED.{c}, updated_at = now()"
    ).format(c=col)
    conn.execute(q, (slug, on))


def _setting_column(name: str) -> sql.Identifier:
    if name not in SETTINGS:  # column names can't be query parameters: only known ones get through
        raise ValueError(f"unknown setting {name!r}")
    return sql.Identifier(name)

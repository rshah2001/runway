"""Send and request money between people connected to you — any time, for anything ("$50 for the festival").

Connected means: you share a named circle (both active members) or have a support agreement (any state
other than stopped). Sending is a real Nessie move (transfer + deposit), journaled before it's sent and
paid once per tap. A request waits for the other person: only they can pay it, from their own account,
and a claim (open → settling) makes double payment impossible. A request carries only the amount and the
note the requester wrote — never a balance or a reason.
"""

import secrets
from datetime import datetime
from decimal import Decimal
from typing import Any

import psycopg

from app.cashflow import LOCAL_TZ

Row = dict[str, Any]

SCHEMA = """
CREATE TABLE IF NOT EXISTS person_payments (
    id           text PRIMARY KEY,
    from_slug    text NOT NULL REFERENCES personas (slug) ON DELETE CASCADE,
    to_slug      text NOT NULL REFERENCES personas (slug) ON DELETE CASCADE,
    amount       numeric(12, 2) NOT NULL CHECK (amount > 0),
    memo         text NOT NULL,
    ts           timestamptz NOT NULL DEFAULT now(),
    transfer_id  text,
    deposit_id   text,
    request_id   text,
    CHECK (from_slug <> to_slug)
);
CREATE INDEX IF NOT EXISTS person_payments_from ON person_payments (from_slug, ts DESC);
CREATE INDEX IF NOT EXISTS person_payments_to ON person_payments (to_slug, ts DESC);
CREATE TABLE IF NOT EXISTS person_requests (
    id          text PRIMARY KEY,
    from_slug   text NOT NULL REFERENCES personas (slug) ON DELETE CASCADE,  -- who asks
    to_slug     text NOT NULL REFERENCES personas (slug) ON DELETE CASCADE,  -- who is asked (and pays)
    amount      numeric(12, 2) NOT NULL CHECK (amount > 0),
    memo        text NOT NULL,
    status      text NOT NULL CHECK (status IN ('open', 'settling', 'paid', 'declined', 'cancelled', 'failed')),
    created_at  timestamptz NOT NULL DEFAULT now(),
    payment_id  text,
    CHECK (from_slug <> to_slug)
);
CREATE INDEX IF NOT EXISTS person_requests_to ON person_requests (to_slug, status);
CREATE INDEX IF NOT EXISTS person_requests_from ON person_requests (from_slug, status);
"""


class NotConnected(PermissionError):
    """You can only send to or ask people in your circles or agreements (message safe to show)."""


class RequestClosed(LookupError):
    """The request isn't open (already paid, declined, or not yours to answer)."""


def people(conn: psycopg.Connection, me: str) -> list[Row]:
    """Everyone connected to `me`, with how: [{slug, name, how}] (names only — never money)."""
    rows = conn.execute(
        """SELECT p.slug, p.first_name AS name, string_agg(DISTINCT how, ', ') AS how FROM (
             SELECT o.slug, c.name AS how FROM circle_members m
               JOIN circle_members o ON o.circle_id = m.circle_id AND o.slug <> m.slug AND o.state = 'active'
               JOIN circles c ON c.id = m.circle_id
               WHERE m.slug = %(me)s AND m.state = 'active'
             UNION
             SELECT CASE WHEN a.supporter = %(me)s THEN a.recipient ELSE a.supporter END, 'Safety net'
               FROM support_agreements a
               WHERE (a.supporter = %(me)s OR a.recipient = %(me)s)
                 AND NOT (a.revoked_at IS NOT NULL
                          AND a.supporter_consent_at IS NULL AND a.recipient_consent_at IS NULL)
           ) x JOIN personas p ON p.slug = x.slug
           GROUP BY p.slug, p.first_name ORDER BY p.first_name""",
        {"me": me},
    ).fetchall()
    return rows


def connected(conn: psycopg.Connection, me: str, other: str) -> bool:
    return other != me and any(r["slug"] == other for r in people(conn, me))


def new_request(conn: psycopg.Connection, me: str, other: str, amount: Decimal, memo: str) -> Row:
    if not connected(conn, me, other):
        raise NotConnected("You can only ask people in your circles.")
    row = {
        "id": f"preq-{secrets.token_hex(6)}",
        "from_slug": me,
        "to_slug": other,
        "amount": amount,
        "memo": memo,
        "created_at": datetime.now(LOCAL_TZ),
    }
    conn.execute(
        """INSERT INTO person_requests (id, from_slug, to_slug, amount, memo, status, created_at)
           VALUES (%(id)s, %(from_slug)s, %(to_slug)s, %(amount)s, %(memo)s, 'open', %(created_at)s)""",
        row,
    )
    return {**row, "status": "open"}


def claim(conn: psycopg.Connection, request_id: str, payer: str) -> Row | None:
    """Atomically open → settling, only by the person asked. None if it isn't theirs or isn't open."""
    return conn.execute(
        """UPDATE person_requests SET status = 'settling' WHERE id = %s AND to_slug = %s AND status = 'open'
           RETURNING *""",
        (request_id, payer),
    ).fetchone()


def finish(conn: psycopg.Connection, request_id: str, status: str, payment_id: str | None = None) -> None:
    conn.execute(
        "UPDATE person_requests SET status = %s, payment_id = COALESCE(%s, payment_id) WHERE id = %s",
        (status, payment_id, request_id),
    )


def answer_decline(conn: psycopg.Connection, request_id: str, payer: str) -> bool:
    row = conn.execute(
        """UPDATE person_requests SET status = 'declined' WHERE id = %s AND to_slug = %s AND status = 'open'
           RETURNING id""",
        (request_id, payer),
    ).fetchone()
    return row is not None


def record_payment(conn: psycopg.Connection, row: Row) -> None:
    conn.execute(
        """INSERT INTO person_payments (id, from_slug, to_slug, amount, memo, transfer_id, deposit_id, request_id)
           VALUES (%(id)s, %(from_slug)s, %(to_slug)s, %(amount)s, %(memo)s, %(transfer_id)s, %(deposit_id)s,
                   %(request_id)s) ON CONFLICT (id) DO NOTHING""",
        {"request_id": None, **row},
    )


def mine(conn: psycopg.Connection, me: str) -> dict[str, list[Row]]:
    """My open requests both ways and my recent payments both ways (names, amounts, notes — nothing else)."""
    names = "JOIN personas f ON f.slug = r.from_slug JOIN personas t ON t.slug = r.to_slug"
    asked_me = conn.execute(
        f"""SELECT r.*, f.first_name AS from_name, t.first_name AS to_name FROM person_requests r {names}
            WHERE r.to_slug = %s AND r.status IN ('open', 'settling') ORDER BY r.created_at DESC""",
        (me,),
    ).fetchall()
    i_asked = conn.execute(
        f"""SELECT r.*, f.first_name AS from_name, t.first_name AS to_name FROM person_requests r {names}
            WHERE r.from_slug = %s ORDER BY r.created_at DESC LIMIT 10""",
        (me,),
    ).fetchall()
    pays = conn.execute(
        """SELECT p.*, f.first_name AS from_name, t.first_name AS to_name FROM person_payments p
           JOIN personas f ON f.slug = p.from_slug JOIN personas t ON t.slug = p.to_slug
           WHERE p.from_slug = %s OR p.to_slug = %s ORDER BY p.ts DESC LIMIT 15""",
        (me, me),
    ).fetchall()
    return {"asked_me": asked_me, "i_asked": i_asked, "payments": pays}


# ---------- moving the money (journaled, once per tap / once per request) ----------
def send(me: str, other: str, amount: Decimal, memo: str, *, key: str, request_id: str | None = None) -> Row:
    """Move `amount` from `me` to `other` in Nessie and record it. Raises TransferNotMade (nothing moved)
    or another error (outcome unclear: journaled `unknown`, reconciled, never retried)."""
    from app.data import _resync
    from app.db import journal_repo, pool, repo
    from app.nessie.client import NessieClient
    from app.nessie.moves import TransferNotMade, move_money

    payment_id = f"ppay-{secrets.token_hex(6)}"
    today = datetime.now(LOCAL_TZ).date()
    with pool.connection() as conn:
        sender, receiver = repo.persona(conn, me), repo.persona(conn, other)
        if not journal_repo.claim(
            conn, key, "p2p", payment_id, sender["checking_id"], receiver["checking_id"], float(amount)
        ):
            conn.rollback()
            raise RequestClosed("That payment is already being sent.")
        conn.commit()
    nessie = NessieClient.from_settings()
    try:
        t_id, d_id = move_money(
            nessie,
            sender["checking_id"],
            receiver["checking_id"],
            float(amount),
            today,
            memo,
            f"From {sender['first_name']}: {memo}",
            key=key,
        )
    except TransferNotMade as e:
        with pool.connection() as conn:
            journal_repo.finish(conn, key, "not_made", error=str(e))
            conn.commit()
        raise
    except Exception as e:
        with pool.connection() as conn:
            journal_repo.finish(conn, key, "unknown", error=str(e))
            conn.commit()
        raise
    row = {
        "id": payment_id,
        "from_slug": me,
        "to_slug": other,
        "amount": amount,
        "memo": memo,
        "transfer_id": t_id,
        "deposit_id": d_id,
        "request_id": request_id,
    }
    with pool.connection() as conn:
        record_payment(conn, row)
        journal_repo.finish(conn, key, "succeeded", transfer_id=t_id, deposit_id=d_id)
        conn.commit()
    for slug in (me, other):
        with pool.connection() as conn:
            _resync(nessie, repo.persona(conn, slug)["customer_id"])
    return row

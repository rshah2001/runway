"""Queries for the family safety net (limits, bridges, the shared activity feed)."""

from typing import Any

import psycopg

Row = dict[str, Any]
OUTSTANDING = ("active", "repaying", "repay_failed")  # money that hasn't come back yet
OPEN = ("pending_approval", *OUTSTANDING)
SETTABLE = {
    "funded_at",
    "repaid_at",
    "auth_req_id",
    "approval_channel",
    "out_transfer_id",
    "out_deposit_id",
    "back_transfer_id",
    "back_deposit_id",
}


# ---------- limits (only ever written on behalf of the lender) ----------
def set_limit(conn: psycopg.Connection, lender: str, borrower: str, amount: float, enabled: bool) -> None:
    conn.execute(
        """INSERT INTO safety_limits (lender_slug, borrower_slug, limit_amount, enabled)
           VALUES (%s, %s, %s, %s)
           ON CONFLICT (lender_slug, borrower_slug) DO UPDATE
             SET limit_amount = EXCLUDED.limit_amount, enabled = EXCLUDED.enabled, updated_at = now()""",
        (lender, borrower, amount, enabled),
    )


def seed_limit(conn: psycopg.Connection, lender: str, borrower: str, amount: float) -> None:
    """Default limit for the demo — never overwrites one a lender has changed."""
    conn.execute(
        """INSERT INTO safety_limits (lender_slug, borrower_slug, limit_amount) VALUES (%s, %s, %s)
           ON CONFLICT DO NOTHING""",
        (lender, borrower, amount),
    )


def limits(conn: psycopg.Connection, *, lender: str | None = None, borrower: str | None = None) -> list[Row]:
    """Limits with what is still outstanding under each (money lent and not yet repaid)."""
    return conn.execute(
        """SELECT l.*, lp.first_name AS lender_name, bp.first_name AS borrower_name,
                  COALESCE((SELECT sum(b.amount) FROM bridges b
                            WHERE b.lender_slug = l.lender_slug AND b.borrower_slug = l.borrower_slug
                              AND b.status = ANY(%s)), 0) AS outstanding
           FROM safety_limits l
           JOIN personas lp ON lp.slug = l.lender_slug
           JOIN personas bp ON bp.slug = l.borrower_slug
           WHERE (%s::text IS NULL OR l.lender_slug = %s) AND (%s::text IS NULL OR l.borrower_slug = %s)
           ORDER BY l.lender_slug, l.borrower_slug""",
        (list(OUTSTANDING), lender, lender, borrower, borrower),
    ).fetchall()


# ---------- bridges ----------
_BRIDGE = """SELECT b.*, lp.first_name AS lender_name, bp.first_name AS borrower_name FROM bridges b
             JOIN personas lp ON lp.slug = b.lender_slug JOIN personas bp ON bp.slug = b.borrower_slug"""


def insert_bridge(conn: psycopg.Connection, b: Row) -> None:
    conn.execute(
        """INSERT INTO bridges (id, borrower_slug, lender_slug, amount, reason, status, mode, shortfall_date, due_date,
                                approval_channel)
           VALUES (%(id)s, %(borrower_slug)s, %(lender_slug)s, %(amount)s, %(reason)s, %(status)s, %(mode)s,
                   %(shortfall_date)s, %(due_date)s, %(approval_channel)s)""",
        b,
    )


def bridge(conn: psycopg.Connection, bridge_id: str) -> Row | None:
    return conn.execute(f"{_BRIDGE} WHERE b.id = %s", (bridge_id,)).fetchone()


def bridges_for(conn: psycopg.Connection, slug: str) -> list[Row]:
    return conn.execute(
        f"{_BRIDGE} WHERE b.borrower_slug = %s OR b.lender_slug = %s ORDER BY b.created_at DESC", (slug, slug)
    ).fetchall()


def open_bridge_for_borrower(conn: psycopg.Connection, borrower: str) -> Row | None:
    return conn.execute(
        f"{_BRIDGE} WHERE b.borrower_slug = %s AND b.status = ANY(%s) LIMIT 1", (borrower, list(OPEN))
    ).fetchone()


def outstanding_bridges(conn: psycopg.Connection) -> list[Row]:
    return conn.execute(f"{_BRIDGE} WHERE b.status = ANY(%s) ORDER BY b.due_date", (list(OUTSTANDING),)).fetchall()


def pending_approvals(conn: psycopg.Connection, lender: str | None = None) -> list[Row]:
    return conn.execute(
        f"{_BRIDGE} WHERE b.status = 'pending_approval' AND (%s::text IS NULL OR b.lender_slug = %s)"
        " ORDER BY b.created_at",
        (lender, lender),
    ).fetchall()


def transition(
    conn: psycopg.Connection, bridge_id: str, from_status: tuple[str, ...], to_status: str, **fields
) -> Row | None:
    """Atomic compare-and-set: move a bridge only if it is still in one of `from_status`. Returns
    the updated row, or None if someone else already moved it — so money never moves twice."""
    unknown = set(fields) - SETTABLE
    if unknown:  # column names are interpolated below, so only ever accept known ones
        raise ValueError(f"not settable: {sorted(unknown)}")
    sets = "".join(f", {k} = %({k})s" for k in fields)
    sql = f"UPDATE bridges SET status = %(to)s{sets} WHERE id = %(id)s AND status = ANY(%(frm)s) RETURNING id"
    row = conn.execute(sql, {"to": to_status, "id": bridge_id, "frm": list(from_status), **fields}).fetchone()
    return bridge(conn, bridge_id) if row else None


def forget(conn: psycopg.Connection, slug: str) -> None:
    """Drop bridges and feed entries involving a persona (used when re-seeding it)."""
    conn.execute("DELETE FROM bridges WHERE borrower_slug = %s OR lender_slug = %s", (slug, slug))
    conn.execute("DELETE FROM safety_events WHERE persona_slug = %s", (slug,))


# ---------- activity feed ----------
def add_event(conn: psycopg.Connection, slug: str, kind: str, message: str, bridge_id: str | None = None) -> None:
    conn.execute(
        "INSERT INTO safety_events (persona_slug, kind, message, bridge_id) VALUES (%s, %s, %s, %s)",
        (slug, kind, message, bridge_id),
    )


def events(conn: psycopg.Connection, slug: str, limit: int = 30) -> list[Row]:
    return conn.execute(
        "SELECT * FROM safety_events WHERE persona_slug = %s ORDER BY at DESC, id DESC LIMIT %s", (slug, limit)
    ).fetchall()

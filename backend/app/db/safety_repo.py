"""Queries for the family safety net (limits, bridges, the shared activity feed)."""

from decimal import Decimal
from typing import Any

import psycopg

Row = dict[str, Any]
OUTSTANDING = ("active", "repaying", "repay_failed", "reconcile")  # money that hasn't (certainly) come back yet
OPEN = ("pending_approval", "funding", *OUTSTANDING)  # anything that still commits a supporter's money
UNFUNDED = ("pending_approval", "funding")  # committed, but not yet out of the supporter's balance
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


# ---------- locking ----------
def lock_people(conn: psycopg.Connection, *slugs: str) -> None:
    """Hold a transaction-scoped lock on each person, always in the same (sorted) order so two passes
    can't deadlock. Every decision that moves or commits someone's money takes these first, so two
    passes can never both spend the same supporter's room. Released at commit/rollback — so the claim
    is committed before the slow Nessie call, never held across it."""
    conn.execute("SET LOCAL lock_timeout = '10s'")
    for slug in sorted(set(slugs)):
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"runway:{slug}",))


# ---------- limits (only ever written on behalf of the lender) ----------
def set_limit(conn: psycopg.Connection, lender: str, borrower: str, amount: float, enabled: bool) -> None:
    conn.execute(
        """INSERT INTO safety_limits (lender_slug, borrower_slug, limit_amount, enabled)
           VALUES (%s, %s, %s, %s)
           ON CONFLICT (lender_slug, borrower_slug) DO UPDATE
             SET limit_amount = EXCLUDED.limit_amount, enabled = EXCLUDED.enabled, updated_at = now()""",
        (lender, borrower, amount, enabled),
    )


def seed_limit(conn: psycopg.Connection, lender: str, borrower: str, amount: float, enabled: bool = True) -> None:
    """Default limit for the demo — never overwrites one a lender has changed."""
    conn.execute(
        """INSERT INTO safety_limits (lender_slug, borrower_slug, limit_amount, enabled) VALUES (%s, %s, %s, %s)
           ON CONFLICT DO NOTHING""",
        (lender, borrower, amount, enabled),
    )


def record_decision(conn: psycopg.Connection, decision_id: str, d: Any, covered: Decimal, version: str) -> None:
    """Write one decision to the audit trail (idempotent on its id)."""
    import json

    conn.execute(
        """INSERT INTO support_decisions
             (id, borrower, action, need, covered, allocations, held, reason, algorithm_version)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING""",
        (
            decision_id,
            d.borrower,
            d.action,
            d.amount,
            covered,
            json.dumps([[s, str(a)] for s, a in d.allocations]),
            json.dumps([[s, why] for s, _, why in d.held]),
            d.reason,
            version,
        ),
    )


def committed_by(conn: psycopg.Connection, lender: str) -> float:
    """Everything this supporter has committed right now (waiting, being sent, or out)."""
    row = conn.execute(
        "SELECT COALESCE(sum(amount), 0) AS total FROM bridges WHERE lender_slug = %s AND status = ANY(%s)",
        (lender, list(OPEN)),
    ).fetchone()
    return float(row["total"])


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


def repay_part(
    conn: psycopg.Connection,
    bridge_id: str,
    from_status: tuple[str, ...],
    back_to: str,
    amount: Decimal,
    t_id: str | None,
    d_id: str | None,
) -> Row | None:
    """Settle part of a bridge: the open bridge's amount drops by `amount` and it goes back to `back_to`;
    the part paid becomes its own closed 'repaid' row (part_of = the bridge). One compare-and-set, like
    `transition`. Returns the part row, or None if the bridge moved or the part isn't smaller than it."""
    left = conn.execute(
        """UPDATE bridges SET amount = amount - %(amt)s, status = %(to)s, status_changed_at = now()
           WHERE id = %(id)s AND status = ANY(%(frm)s) AND amount > %(amt)s RETURNING id""",
        {"amt": amount, "to": back_to, "id": bridge_id, "frm": list(from_status)},
    ).fetchone()
    if left is None:
        return None
    n = conn.execute("SELECT count(*) AS n FROM bridges WHERE part_of = %s", (bridge_id,)).fetchone()["n"]
    part_id = f"{bridge_id}-p{n + 1}"
    conn.execute(
        """INSERT INTO bridges (id, borrower_slug, lender_slug, amount, reason, status, mode, shortfall_date,
                                due_date, created_at, funded_at, repaid_at, approval_channel, borrower_floor,
                                agreement_version, decision_id, back_transfer_id, back_deposit_id, part_of)
           SELECT %(part)s, borrower_slug, lender_slug, %(amt)s, reason, 'repaid', mode, shortfall_date,
                  due_date, created_at, funded_at, now(), approval_channel, borrower_floor,
                  agreement_version, decision_id, %(t)s, %(d)s, id
           FROM bridges WHERE id = %(id)s""",
        {"part": part_id, "amt": amount, "t": t_id, "d": d_id, "id": bridge_id},
    )
    return bridge(conn, part_id)


def insert_bridge(conn: psycopg.Connection, b: Row) -> None:
    conn.execute(
        """INSERT INTO bridges (id, borrower_slug, lender_slug, amount, reason, status, mode, shortfall_date, due_date,
                                approval_channel, borrower_floor, agreement_version, decision_id)
           VALUES (%(id)s, %(borrower_slug)s, %(lender_slug)s, %(amount)s, %(reason)s, %(status)s, %(mode)s,
                   %(shortfall_date)s, %(due_date)s, %(approval_channel)s, %(borrower_floor)s,
                   %(agreement_version)s, %(decision_id)s)""",
        {"borrower_floor": None, "agreement_version": None, "decision_id": None, **b},
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


def open_bridges(conn: psycopg.Connection) -> list[Row]:
    """Every bridge that still commits someone's money: waiting for approval, being sent, or out."""
    return conn.execute(f"{_BRIDGE} WHERE b.status = ANY(%s) ORDER BY b.due_date", (list(OPEN),)).fetchall()


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
    sql = (
        f"UPDATE bridges SET status = %(to)s, status_changed_at = now(){sets}"
        " WHERE id = %(id)s AND status = ANY(%(frm)s) RETURNING id"
    )
    row = conn.execute(sql, {"to": to_status, "id": bridge_id, "frm": list(from_status), **fields}).fetchone()
    return bridge(conn, bridge_id) if row else None


def unsettled(conn: psycopg.Connection, slug: str) -> bool:
    """True while a money move involving this persona is unclear — a reseed must not delete its accounts."""
    row = conn.execute(
        """SELECT 1 FROM bridges b WHERE (b.borrower_slug = %s OR b.lender_slug = %s)
             AND (b.status IN ('funding', 'repaying', 'reconcile')
                  OR EXISTS (SELECT 1 FROM transfer_journal j WHERE j.ref = b.id AND j.state IN ('started', 'unknown')))
           LIMIT 1""",
        (slug, slug),
    ).fetchone()
    return row is not None


def forget(conn: psycopg.Connection, slug: str) -> None:
    """Drop bridges and feed entries involving a persona (used when re-seeding it)."""
    conn.execute(
        "DELETE FROM transfer_journal WHERE ref IN"
        " (SELECT id FROM bridges WHERE borrower_slug = %s OR lender_slug = %s)",
        (slug, slug),
    )
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

"""Queries for Quiet Support Agreements (consent) and their audit trail. Rules live in app/agreements.py."""

import json
from typing import Any

import psycopg

Row = dict[str, Any]

_SELECT = """SELECT a.*, sp.first_name AS supporter_name, rp.first_name AS recipient_name,
                    l.limit_amount, l.enabled,
                    COALESCE((SELECT sum(b.amount) FROM bridges b
                              WHERE b.lender_slug = a.supporter AND b.borrower_slug = a.recipient
                                AND b.status = ANY(%(outstanding)s)), 0) AS outstanding
             FROM support_agreements a
             JOIN personas sp ON sp.slug = a.supporter
             JOIN personas rp ON rp.slug = a.recipient
             LEFT JOIN safety_limits l ON l.lender_slug = a.supporter AND l.borrower_slug = a.recipient"""
_OUTSTANDING = ["active", "repaying", "repay_failed", "reconcile"]


def get(conn: psycopg.Connection, supporter: str, recipient: str) -> Row | None:
    return conn.execute(
        f"{_SELECT} WHERE a.supporter = %(s)s AND a.recipient = %(r)s",
        {"s": supporter, "r": recipient, "outstanding": _OUTSTANDING},
    ).fetchone()


def involving(conn: psycopg.Connection, slug: str) -> list[Row]:
    """Every agreement where `slug` is the supporter or the recipient."""
    return conn.execute(
        f"{_SELECT} WHERE a.supporter = %(p)s OR a.recipient = %(p)s ORDER BY a.supporter, a.recipient",
        {"p": slug, "outstanding": _OUTSTANDING},
    ).fetchall()


def ensure(conn: psycopg.Connection, supporter: str, recipient: str) -> None:
    conn.execute(
        "INSERT INTO support_agreements (supporter, recipient) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        (supporter, recipient),
    )


def stamp(conn: psycopg.Connection, supporter: str, recipient: str, side: str, source: str) -> None:
    """Record one side's consent (and lift a revocation: consent after revoking starts over)."""
    if side not in ("supporter", "recipient"):  # interpolated below
        raise ValueError(side)
    conn.execute(
        f"""UPDATE support_agreements SET {side}_consent_at = now(), {side}_consent_source = %s,
                   revoked_at = NULL, revoked_by = NULL, version = version + 1, updated_at = now()
            WHERE supporter = %s AND recipient = %s""",
        (source, supporter, recipient),
    )


def revoke(conn: psycopg.Connection, supporter: str, recipient: str, actor: str) -> None:
    """Withdraw consent on both sides: help can only resume after both say yes again."""
    conn.execute(
        """UPDATE support_agreements SET supporter_consent_at = NULL, supporter_consent_source = NULL,
                  recipient_consent_at = NULL, recipient_consent_source = NULL,
                  revoked_at = now(), revoked_by = %s, version = version + 1, updated_at = now()
           WHERE supporter = %s AND recipient = %s""",
        (actor, supporter, recipient),
    )


def set_mode(conn: psycopg.Connection, supporter: str, recipient: str, mode: str) -> None:
    conn.execute(
        """UPDATE support_agreements SET mode = %s, version = version + 1, updated_at = now()
           WHERE supporter = %s AND recipient = %s""",
        (mode, supporter, recipient),
    )


def bump(conn: psycopg.Connection, supporter: str, recipient: str) -> None:
    conn.execute(
        """UPDATE support_agreements SET version = version + 1, updated_at = now()
           WHERE supporter = %s AND recipient = %s""",
        (supporter, recipient),
    )


def audit(conn: psycopg.Connection, supporter: str, recipient: str, actor: str, action: str, **detail) -> None:
    conn.execute(
        """INSERT INTO support_agreement_events (supporter, recipient, actor, action, detail)
           VALUES (%s, %s, %s, %s, %s)""",
        (supporter, recipient, actor, action, json.dumps(detail, default=str)),
    )

"""The transfer journal: one row per money move, written before the Nessie call (see schema JOURNAL)."""

from datetime import timedelta
from typing import Any

import psycopg

Row = dict[str, Any]
OPEN = ("started", "unknown")  # the outcome isn't settled yet


def claim(
    conn: psycopg.Connection, key: str, kind: str, ref: str, from_account: str, to_account: str, amount: float
) -> bool:
    """Record a move about to happen. False if `key` was already used — that move must not be sent again."""
    row = conn.execute(
        """INSERT INTO transfer_journal (key, kind, ref, from_account, to_account, amount, state)
           VALUES (%s, %s, %s, %s, %s, %s, 'started') ON CONFLICT (key) DO NOTHING RETURNING key""",
        (key, kind, ref, from_account, to_account, amount),
    ).fetchone()
    return row is not None


def finish(
    conn: psycopg.Connection,
    key: str,
    state: str,
    *,
    transfer_id: str | None = None,
    deposit_id: str | None = None,
    error: str | None = None,
) -> bool:
    """Settle a move — only from an open state, so a late answer can't overwrite a settled one."""
    row = conn.execute(
        """UPDATE transfer_journal SET state = %s, transfer_id = COALESCE(%s, transfer_id),
                  deposit_id = COALESCE(%s, deposit_id), error = COALESCE(%s, error), updated_at = now()
           WHERE key = %s AND state = ANY(%s) RETURNING key""",
        (state, transfer_id, deposit_id, error, key, list(OPEN)),
    ).fetchone()
    return row is not None


def get(conn: psycopg.Connection, key: str) -> Row | None:
    return conn.execute("SELECT * FROM transfer_journal WHERE key = %s", (key,)).fetchone()


def for_ref(conn: psycopg.Connection, ref: str, kind: str) -> list[Row]:
    return conn.execute(
        "SELECT * FROM transfer_journal WHERE ref = %s AND kind = %s ORDER BY created_at", (ref, kind)
    ).fetchall()


def unresolved(conn: psycopg.Connection, older_than: timedelta) -> list[Row]:
    """Open moves untouched for `older_than` — long past any in-flight Nessie call."""
    return conn.execute(
        """SELECT * FROM transfer_journal WHERE state = ANY(%s) AND updated_at < now() - %s
           ORDER BY created_at""",
        (list(OPEN), older_than),
    ).fetchall()

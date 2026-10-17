"""Quiet Support Agreements — the consent behind every automatic transfer.

A supporter's limit says how much; an agreement says both people agreed. Runway may move money
automatically only when the agreement is *active*: the supporter said yes, the recipient said yes,
nobody has revoked it, and the supporter hasn't paused it (limit switched off). Either person can
revoke at any time; help then waits for both to agree again. Revoking stops new help; it never erases
money already lent (that is still repaid on payday).

Joining a Circle grants none of this — membership and money consent are separate on purpose.
"""

from typing import Literal

import psycopg

from app.db import agreements_repo

Side = Literal["supporter", "recipient"]
State = Literal["active", "paused", "needs_supporter", "needs_recipient", "needs_both", "revoked"]


class NotYourAgreement(PermissionError):
    """The signed-in person isn't the side that may make this change."""


def state(row: dict) -> State:
    """What an agreement row means right now."""
    s, r = row["supporter_consent_at"] is not None, row["recipient_consent_at"] is not None
    if row["revoked_at"] is not None and not (s or r):
        return "revoked"
    if s and r:
        return "active" if row.get("enabled", True) is not False and row.get("limit_amount") is not None else "paused"
    if s:
        return "needs_recipient"
    if r:
        return "needs_supporter"
    return "needs_both"


def is_active(row: dict | None) -> bool:
    return row is not None and state(row) == "active"


def side_of(actor: str, supporter: str, recipient: str) -> Side:
    if actor == supporter:
        return "supporter"
    if actor == recipient:
        return "recipient"
    raise NotYourAgreement(f"{actor} is not part of {supporter} → {recipient}")


def consent(conn: psycopg.Connection, actor: str, supporter: str, recipient: str, source: str = "in_app") -> dict:
    """`actor` says yes to their own side of supporter → recipient."""
    if supporter == recipient:
        raise NotYourAgreement("You can't support yourself")
    side = side_of(actor, supporter, recipient)
    agreements_repo.ensure(conn, supporter, recipient)
    agreements_repo.stamp(conn, supporter, recipient, side, source)
    agreements_repo.audit(conn, supporter, recipient, actor, f"{side}_consented", source=source)
    return agreements_repo.get(conn, supporter, recipient)


def revoke(conn: psycopg.Connection, actor: str, supporter: str, recipient: str) -> dict:
    """Either person withdraws. Money already out still comes back on payday."""
    side_of(actor, supporter, recipient)
    agreements_repo.revoke(conn, supporter, recipient, actor)
    agreements_repo.audit(conn, supporter, recipient, actor, "revoked")
    return agreements_repo.get(conn, supporter, recipient)


def limit_changed(conn: psycopg.Connection, supporter: str, recipient: str, limit: float, enabled: bool) -> None:
    """The supporter set their limit in the app: that is the supporter's explicit authorization (unlike a
    migrated legacy limit), and any change bumps the version so a waiting approval re-checks it."""
    agreements_repo.ensure(conn, supporter, recipient)
    row = agreements_repo.get(conn, supporter, recipient)
    if enabled and limit > 0 and row["supporter_consent_at"] is None:
        agreements_repo.stamp(conn, supporter, recipient, "supporter", "set_limit")
    else:
        agreements_repo.bump(conn, supporter, recipient)
    agreements_repo.audit(conn, supporter, recipient, supporter, "limit_set", limit=limit, enabled=enabled)


def setup_demo(conn: psycopg.Connection, pairs: list[tuple[str, str]], *, force: bool = False) -> int:
    """Record both consents for the scripted demo relationships, auditably (source 'demo_setup').
    Without `force`, a pair someone has acted on (consented or revoked) is left alone, so the nightly
    reseed never overrides a person's own choice. Returns how many pairs were set up."""
    done = 0
    for supporter, recipient in pairs:
        agreements_repo.ensure(conn, supporter, recipient)
        row = agreements_repo.get(conn, supporter, recipient)
        untouched = row["supporter_consent_at"] is None and row["recipient_consent_at"] is None
        if not force and (row["revoked_at"] is not None or not untouched):
            continue
        for side in ("supporter", "recipient"):
            agreements_repo.stamp(conn, supporter, recipient, side, "demo_setup")
        agreements_repo.audit(conn, supporter, recipient, "demo_setup", "both_consented_for_demo")
        done += 1
    return done

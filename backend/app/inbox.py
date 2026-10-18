"""In-app notifications for circles: "Sam added you to Family", "Maya joined Family".

Being added to a circle shows up by itself — a pop-up on whatever screen you're on, with Join / Decline —
instead of relying on a link someone has to send you. Both ends hear about it: the person added, and,
when they answer, the person who added them (and the circle's creator, for someone joining by link).

A row is written in the same transaction as the circle change, so a notification can never describe
something that didn't happen. Phone push (Web Push, app/alerts.py) goes out afterwards, best effort, once
per row; with "discreet notifications" on (the default) the lock screen says only that there's an update.
Notifications carry names and the circle's name — never money. The circle's name (free text) stays in the
app; a lock screen gets at most "Sam added you to a circle". Invitations are capped per person per hour.
"""

import logging
import secrets
import threading
from typing import Any

import psycopg

Row = dict[str, Any]
log = logging.getLogger(__name__)

KINDS = ("circle_invite", "circle_joined", "circle_declined")

SCHEMA = """
CREATE TABLE IF NOT EXISTS inbox (
    id          text PRIMARY KEY,
    slug        text NOT NULL REFERENCES personas (slug) ON DELETE CASCADE,  -- who it's for
    kind        text NOT NULL CHECK (kind IN ('circle_invite', 'circle_joined', 'circle_declined')),
    circle_id   text NOT NULL REFERENCES circles (id) ON DELETE CASCADE,
    actor       text NOT NULL REFERENCES personas (slug) ON DELETE CASCADE,  -- who did it
    created_at  timestamptz NOT NULL DEFAULT now(),
    seen_at     timestamptz,
    pushed_at   timestamptz
);
CREATE INDEX IF NOT EXISTS inbox_unseen ON inbox (slug, created_at DESC) WHERE seen_at IS NULL;
"""


def add(conn: psycopg.Connection, slug: str, kind: str, circle_id: str, actor: str) -> None:
    """Tell `slug` that `actor` did `kind` in this circle (never to yourself)."""
    if slug == actor:
        return
    if kind == "circle_invite":  # a newer invitation to the same circle replaces an unanswered one
        conn.execute(
            "UPDATE inbox SET seen_at = now() WHERE slug = %s AND circle_id = %s AND kind = 'circle_invite' "
            "AND seen_at IS NULL",
            (slug, circle_id),
        )
    conn.execute(
        "INSERT INTO inbox (id, slug, kind, circle_id, actor) VALUES (%s, %s, %s, %s, %s)",
        (f"note-{secrets.token_hex(6)}", slug, kind, circle_id, actor),
    )


def sent_recently(conn: psycopg.Connection, actor: str) -> int:
    """Invitations `actor` sent in the last hour (the anti-spam cap in circles.invite)."""
    row = conn.execute(
        "SELECT count(*) AS n FROM inbox WHERE actor = %s AND kind = 'circle_invite' "
        "AND created_at > now() - interval '1 hour'",
        (actor,),
    ).fetchone()
    return int(row["n"]) if row else 0


def mine(conn: psycopg.Connection, slug: str, limit: int = 10) -> list[Row]:
    """Unseen notifications, newest first. An invitation already answered (or withdrawn) drops out."""
    rows = conn.execute(
        """SELECT n.id, n.kind, n.circle_id, c.name AS circle, a.first_name AS actor_name, n.created_at,
                  m.state AS my_state
           FROM inbox n JOIN circles c ON c.id = n.circle_id JOIN personas a ON a.slug = n.actor
           LEFT JOIN circle_members m ON m.circle_id = n.circle_id AND m.slug = n.slug
           WHERE n.slug = %s AND n.seen_at IS NULL ORDER BY n.created_at DESC LIMIT %s""",
        (slug, limit),
    ).fetchall()
    return [r for r in rows if r["kind"] != "circle_invite" or r["my_state"] == "invited"]


def seen(conn: psycopg.Connection, slug: str, note_id: str) -> None:
    conn.execute("UPDATE inbox SET seen_at = now() WHERE id = %s AND slug = %s", (note_id, slug))


def text(kind: str, actor: str, circle: str) -> str:
    """The words on the pop-up (and on the lock screen, unless discreet)."""
    return {
        "circle_invite": f"{actor} added you to {circle}",
        "circle_joined": f"{actor} joined {circle}",
        "circle_declined": f"{actor} didn't join {circle}",
    }[kind]


def push_new() -> None:
    """Send a phone push for each notification not pushed yet — in the background, never blocking a
    request. Each row is claimed before sending, so two passes can't both push it."""
    threading.Thread(target=_push_new, name="inbox-push", daemon=True).start()


def _push_new() -> None:
    from app import alerts, prefs
    from app.db import pool

    keys = alerts.vapid()
    try:
        with pool.connection() as conn:
            rows = conn.execute(
                """UPDATE inbox n SET pushed_at = now() FROM circles c, personas a
                   WHERE n.pushed_at IS NULL AND n.seen_at IS NULL AND c.id = n.circle_id AND a.slug = n.actor
                   RETURNING n.id, n.slug, n.kind, c.name AS circle, a.first_name AS actor_name"""
            ).fetchall()
            conn.commit()
        if keys is None:
            return  # no push keys configured: the in-app pop-up is the notification
        for r in rows:
            discreet = prefs.setting(r["slug"], "discreet_notifications")
            payload = {
                "title": "Runway",
                # the circle's name is free text someone else typed, so it never reaches a lock screen
                "body": "You have a new circle update." if discreet else text(r["kind"], r["actor_name"], "a circle"),
                "url": "/circles",
                "tag": f"circle-{r['id']}",
            }
            for sub in alerts.subscriptions(r["slug"]):
                alerts.send(sub, payload, keys)
    except Exception:  # a push is a nicety; the pop-up still shows
        log.exception("circle push failed")

"""Named Circles: groups of people who trust each other ("Family", "Weekend crew").

A circle is only a list of people. Joining one grants NOTHING financial — no limit, no consent, no view
of anyone's money: support always needs a Quiet Support Agreement between two people (app/agreements.py).
That separation is the point: being in someone's circle must never mean access to their finances.

Rules: only active members invite; the invited person accepts or declines; anyone can leave; only the
person who made the circle removes others. You only ever see circles you're in or invited to, and in
them only names and who's in — never anything about money.
"""

import secrets
from typing import Any

import psycopg

from app import inbox

Row = dict[str, Any]
STATES = ("invited", "active", "declined", "left", "removed")
VISIBLE = ("invited", "active")  # members listed to other members


class CircleRefused(PermissionError):
    """Not allowed for this person (the message is safe to show)."""


SCHEMA = """
CREATE TABLE IF NOT EXISTS circles (
    id          text PRIMARY KEY,
    name        text NOT NULL CHECK (length(name) BETWEEN 1 AND 40),
    created_by  text NOT NULL REFERENCES personas (slug) ON DELETE CASCADE,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS circle_members (
    circle_id   text NOT NULL REFERENCES circles (id) ON DELETE CASCADE,
    slug        text NOT NULL REFERENCES personas (slug) ON DELETE CASCADE,
    state       text NOT NULL CHECK (state IN ('invited', 'active', 'declined', 'left', 'removed')),
    invited_by  text,
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (circle_id, slug)
);
CREATE INDEX IF NOT EXISTS circle_members_slug ON circle_members (slug, state);
-- invite links: an unguessable token a member shares; opening it (signed in) joins the circle. Expires,
-- can be turned off, and never lets back in someone the creator removed.
CREATE TABLE IF NOT EXISTS circle_invites (
    token       text PRIMARY KEY,
    circle_id   text NOT NULL REFERENCES circles (id) ON DELETE CASCADE,
    created_by  text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    expires_at  timestamptz NOT NULL,
    revoked     boolean NOT NULL DEFAULT false
);
CREATE INDEX IF NOT EXISTS circle_invites_circle ON circle_invites (circle_id);
"""


def _state(conn: psycopg.Connection, circle_id: str, slug: str) -> str | None:
    row = conn.execute(
        "SELECT state FROM circle_members WHERE circle_id = %s AND slug = %s", (circle_id, slug)
    ).fetchone()
    return row["state"] if row else None


def _set(conn: psycopg.Connection, circle_id: str, slug: str, state: str, invited_by: str | None = None) -> None:
    conn.execute(
        """INSERT INTO circle_members (circle_id, slug, state, invited_by) VALUES (%s, %s, %s, %s)
           ON CONFLICT (circle_id, slug) DO UPDATE SET state = EXCLUDED.state,
             invited_by = COALESCE(EXCLUDED.invited_by, circle_members.invited_by), updated_at = now()""",
        (circle_id, slug, state, invited_by),
    )


def _is_creator(conn: psycopg.Connection, circle_id: str, actor: str) -> bool:
    row = conn.execute("SELECT created_by FROM circles WHERE id = %s", (circle_id,)).fetchone()
    return row is not None and row["created_by"] == actor


def create(conn: psycopg.Connection, actor: str, name: str, circle_id: str | None = None) -> str:
    name = name.strip()
    if not 1 <= len(name) <= 40:
        raise CircleRefused("Give the circle a name of up to 40 characters.")
    circle_id = circle_id or f"circle-{secrets.token_hex(5)}"
    conn.execute("INSERT INTO circles (id, name, created_by) VALUES (%s, %s, %s)", (circle_id, name, actor))
    _set(conn, circle_id, actor, "active")
    return circle_id


def invite(conn: psycopg.Connection, actor: str, circle_id: str, slug: str) -> None:
    if _state(conn, circle_id, actor) != "active":
        raise CircleRefused("Only people in this circle can invite someone.")
    if slug == actor:
        raise CircleRefused("You're already in this circle.")
    current = _state(conn, circle_id, slug)
    if current in ("invited", "active"):
        return  # already there or already asked: nothing to do
    # someone the creator removed, or who said no, can only be asked again by the creator — otherwise
    # any member could undo a removal or keep re-inviting a person who declined
    if current in ("removed", "declined") and not _is_creator(conn, circle_id, actor):
        raise CircleRefused("Only the person who made this circle can invite them again.")
    _set(conn, circle_id, slug, "invited", invited_by=actor)
    inbox.add(conn, slug, "circle_invite", circle_id, actor)  # shows up for them — no link needed


def answer(conn: psycopg.Connection, actor: str, circle_id: str, accept: bool) -> None:
    if _state(conn, circle_id, actor) != "invited":
        raise CircleRefused("There's no invitation to answer.")
    _set(conn, circle_id, actor, "active" if accept else "declined")
    row = conn.execute(
        "SELECT invited_by FROM circle_members WHERE circle_id = %s AND slug = %s", (circle_id, actor)
    ).fetchone()
    if row and row["invited_by"]:  # and the person who added them hears the answer
        inbox.add(conn, row["invited_by"], "circle_joined" if accept else "circle_declined", circle_id, actor)


def _revoke_links_by(conn: psycopg.Connection, circle_id: str, slug: str) -> None:
    conn.execute("UPDATE circle_invites SET revoked = true WHERE circle_id = %s AND created_by = %s", (circle_id, slug))


def leave(conn: psycopg.Connection, actor: str, circle_id: str) -> None:
    if _state(conn, circle_id, actor) not in ("invited", "active"):
        raise CircleRefused("You're not in this circle.")
    _set(conn, circle_id, actor, "left")
    _revoke_links_by(conn, circle_id, actor)  # links they shared stop working when they go


def remove(conn: psycopg.Connection, actor: str, circle_id: str, slug: str) -> None:
    if not _is_creator(conn, circle_id, actor) or _state(conn, circle_id, actor) != "active":
        raise CircleRefused("Only the person who made this circle can remove someone.")
    if slug == actor:
        raise CircleRefused("You can leave, but not remove yourself.")
    if _state(conn, circle_id, slug) not in ("invited", "active"):
        raise CircleRefused("They're not in this circle.")
    _set(conn, circle_id, slug, "removed")
    _revoke_links_by(conn, circle_id, slug)  # and any links they shared


def mine(conn: psycopg.Connection, viewer: str) -> list[Row]:
    """Circles `viewer` is in or invited to, each with its visible members (names and states only)."""
    circles = conn.execute(
        """SELECT c.id, c.name, c.created_by, m.state AS my_state FROM circles c
           JOIN circle_members m ON m.circle_id = c.id AND m.slug = %s AND m.state = ANY(%s)
           ORDER BY c.created_at""",
        (viewer, list(VISIBLE)),
    ).fetchall()
    for c in circles:
        c["members"] = conn.execute(
            """SELECT m.slug, p.first_name AS name, m.state FROM circle_members m
               JOIN personas p ON p.slug = m.slug WHERE m.circle_id = %s AND m.state = ANY(%s)
               ORDER BY (m.state = 'active') DESC, p.first_name""",
            (c["id"], list(VISIBLE)),
        ).fetchall()
    return circles


LINK_DAYS = 7


def make_link(conn: psycopg.Connection, actor: str, circle_id: str) -> Row:
    """A fresh invite link for this circle (only its active members can make one)."""
    if _state(conn, circle_id, actor) != "active":
        raise CircleRefused("Only people in this circle can share an invite link.")
    token = secrets.token_urlsafe(18)  # ~144 bits: not guessable, not enumerable
    return conn.execute(
        """INSERT INTO circle_invites (token, circle_id, created_by, expires_at)
           VALUES (%s, %s, %s, now() + make_interval(days => %s)) RETURNING token, expires_at""",
        (token, circle_id, actor, LINK_DAYS),
    ).fetchone()


def link_info(conn: psycopg.Connection, token: str) -> Row | None:
    """What an invite link points at, if it's still valid: the circle's name and who made it — nothing else."""
    return conn.execute(
        """SELECT i.circle_id, c.name, p.first_name AS made_by, i.expires_at FROM circle_invites i
           JOIN circles c ON c.id = i.circle_id JOIN personas p ON p.slug = c.created_by
           -- a link only works while whoever made it is still in the circle
           JOIN circle_members m ON m.circle_id = i.circle_id AND m.slug = i.created_by AND m.state = 'active'
           WHERE i.token = %s AND NOT i.revoked AND i.expires_at > now()""",
        (token,),
    ).fetchone()


def join_by_link(conn: psycopg.Connection, actor: str, token: str) -> str:
    """Join the circle a valid link points at. Someone the creator removed can't come back this way."""
    info = link_info(conn, token)
    if info is None:
        raise CircleRefused("This invite link has expired or been turned off. Ask for a new one.")
    current = _state(conn, info["circle_id"], actor)
    if current == "removed":
        raise CircleRefused("Ask the person who made this circle to invite you again.")
    if current != "active":
        _set(conn, info["circle_id"], actor, "active")
        creator = conn.execute("SELECT created_by FROM circles WHERE id = %s", (info["circle_id"],)).fetchone()
        if creator:
            inbox.add(conn, creator["created_by"], "circle_joined", info["circle_id"], actor)
    return info["circle_id"]


def turn_off_links(conn: psycopg.Connection, actor: str, circle_id: str) -> None:
    """The creator turns off every invite link for their circle."""
    if not _is_creator(conn, circle_id, actor):
        raise CircleRefused("Only the person who made this circle can turn off its links.")
    conn.execute("UPDATE circle_invites SET revoked = true WHERE circle_id = %s", (circle_id,))


# the demo's circles: (id, name, creator, active members, invited members)
DEMO = [
    ("circle-family", "Family", "sam", ("maya", "jordan", "emma"), ()),
    ("circle-weekend", "Weekend crew", "emma", ("maya", "alex"), ("jordan",)),
]


def setup_demo(conn: psycopg.Connection, *, force: bool = False) -> None:
    """Create the demo circles (force: rebuild them from the script, for the demo reset)."""
    for circle_id, name, creator, active, invited in DEMO:
        exists = conn.execute("SELECT 1 FROM circles WHERE id = %s", (circle_id,)).fetchone()
        if exists and not force:
            continue
        conn.execute("DELETE FROM circles WHERE id = %s", (circle_id,))
        create(conn, creator, name, circle_id)
        for slug in active:
            _set(conn, circle_id, slug, "active", invited_by=creator)
        for slug in invited:
            _set(conn, circle_id, slug, "invited", invited_by=creator)
            inbox.add(conn, slug, "circle_invite", circle_id, creator)  # the demo opens on a fresh invitation

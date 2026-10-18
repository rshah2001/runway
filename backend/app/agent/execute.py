"""Carry out an approved action from actions.py, through the same functions the app's own buttons use
(people_pay, safety_net.repay_now, circles). main.py's approve route calls `run` after it has checked
that the person approving is the person it was proposed for, and claimed the action exactly once.

Outside live mode (CI, an offline demo) the approval is the whole story, as for a pause: nothing is
written. A refusal the user should read (not connected, would go under their cushion, only the circle's
creator can…) is raised as ActionRefused; a bank failure is raised as-is, for the route's 503 / 502.
"""

import os
from decimal import Decimal

from app import data
from app.config import get_settings
from app.schemas import PendingAction

SITE = os.getenv("PUBLIC_SITE_URL", "https://sixsevenbucksleft.vip").rstrip("/")


class ActionRefused(Exception):
    """An approved action the backend won't do; the message is safe to show the person."""


def run(action_id: str, action: PendingAction, persona: str, details: dict) -> None:
    """Do what `action` proposed, for `persona` (who already approved it)."""
    if not get_settings().live:
        return
    kind = action.kind
    if kind == "person_send":
        _send(action_id, persona, details["to"], action.amount or 0, details.get("memo", ""))
    elif kind == "person_request":
        _ask(persona, details["to"], action.amount or 0, details.get("memo", ""))
    elif kind == "repay":
        _repay(persona, details["bridge_id"], action.amount)
    elif kind.startswith("circle_"):
        _circle(action, persona, details)
    else:
        raise ActionRefused("This action can't be carried out.")


def _cents(amount: float) -> Decimal:
    return Decimal(str(amount)).quantize(Decimal("0.01"))


def _send(action_id: str, me: str, to: str, amount: float, memo: str) -> None:
    from app import people_pay
    from app.db import pool

    if not data.writes_enabled():
        raise ActionRefused("Real transfers are off right now.")
    with pool.connection() as conn:
        if not people_pay.connected(conn, me, to):  # re-checked: they may have left the circle since
            raise ActionRefused("You can only send to people in your circles.")
    try:
        # one approval = one payment: the key is the action's, so a retry after "nothing moved" can't double it
        people_pay.send(me, to, _cents(amount), memo, key=f"psend:{me}:ai-{action_id}")
    except people_pay.RequestClosed:
        raise ActionRefused("That payment is already being sent.") from None


def _ask(me: str, to: str, amount: float, memo: str) -> None:
    from app import people_pay
    from app.db import pool

    with pool.connection() as conn:
        try:
            people_pay.new_request(conn, me, to, _cents(amount), memo)
        except people_pay.NotConnected as e:
            raise ActionRefused(str(e)) from None
        conn.commit()


def _repay(me: str, bridge_id: str, amount: float | None) -> None:
    from app import safety_net
    from app.db import pool, safety_repo

    if not safety_net.writes_enabled():
        raise ActionRefused("Real transfers are switched off, so nothing can be paid back right now.")
    with pool.connection() as conn:
        b = safety_repo.bridge(conn, bridge_id)
    if b is None or b["borrower_slug"] != me:  # only the person who was covered pays it back
        raise ActionRefused("That support isn't yours to pay back.")
    whole = amount is None or _cents(amount) >= Decimal(b["amount"])  # it may have shrunk since the proposal
    try:
        safety_net.repay_now(bridge_id, None if whole else _cents(amount))
    except safety_net.RepayRefused as e:
        raise ActionRefused(str(e)) from None


def _create_and_invite(circles, conn, me: str, details: dict) -> str:
    """One approval: the circle, then everyone the person asked to invite (same rules as Invite)."""
    circle_id = circles.create(conn, me, details["name"])
    for slug in details.get("invite", []):
        circles.invite(conn, me, circle_id, slug)
    return circle_id


def _circle(action: PendingAction, me: str, details: dict) -> None:
    from app import circles
    from app.db import pool

    cid = details.get("circle", "")
    acts = {
        "circle_create": lambda conn: _create_and_invite(circles, conn, me, details),
        "circle_invite": lambda conn: circles.invite(conn, me, cid, details["slug"]),
        "circle_remove": lambda conn: circles.remove(conn, me, cid, details["slug"]),
        "circle_leave": lambda conn: circles.leave(conn, me, cid),
        "circle_accept": lambda conn: circles.answer(conn, me, cid, True),
        "circle_decline": lambda conn: circles.answer(conn, me, cid, False),
        "circle_link": lambda conn: circles.make_link(conn, me, cid),
    }
    with pool.connection() as conn:
        try:
            result = acts[action.kind](conn)
        except circles.CircleRefused as e:
            raise ActionRefused(str(e)) from None
        conn.commit()
    if action.kind == "circle_link":  # the card shows the link once it exists
        action.description = f"Invite link (works for 7 days): {SITE}/join/{result['token']}"

"""Activity: every support transfer and repayment that involves ONE person, each with a plain "why".

Every explanation is written from the viewer's own side, from facts that are theirs to see: who, how much,
their own limit and cushion, the status, and the bank reference of their own side of the transfer. A
supporter's entries never use the stored decision reason (it names the recipient's projected balance),
and nobody's entry mentions another supporter, a balance or a forecast that isn't theirs.
"""

from datetime import date, datetime
from typing import Any

from app.cashflow import LOCAL_TZ
from app.schemas import ActivityItem

OUT = ("funding", "active", "repaying", "repay_failed", "reconcile")


def _day(v: Any) -> date | None:
    if v is None:
        return None
    return v.astimezone(LOCAL_TZ).date() if isinstance(v, datetime) else v


def _money(x: float) -> str:
    return f"${x:,.2f}".replace(".00", "")


def _wmd(d: date | None) -> str:
    return f"{d:%a %b} {d.day}" if d else "payday"


def item(b: dict, viewer: str, *, my_limit: float | None, my_floor: float) -> ActivityItem:
    """One bridge, as `viewer` (its borrower or its lender) may see it."""
    amt, status = float(b["amount"]), b["status"]
    when = _day(b.get("repaid_at")) or _day(b.get("funded_at")) or _day(b.get("created_at")) or date.today()
    if b["borrower_slug"] == viewer:  # support I received
        them = b["lender_name"]
        ref = b.get("back_transfer_id") if status == "repaid" else b.get("out_deposit_id")
        if status == "repaid":
            return ActivityItem(
                id=b["id"],
                date=when,
                kind="repaid_by_me",
                title=f"You paid {them} back",
                amount=amt,
                status="Repaid",
                why="Runway paid it back after your paycheck landed, and only because it wouldn't take "
                "you under what you keep.",
                reference=ref,
            )
        if status == "pending_approval":
            return ActivityItem(
                id=b["id"],
                date=when,
                kind="waiting",
                title=f"Asked {them} for {_money(amt)}",
                amount=amt,
                status=f"Waiting for {them}",
                why=f"It's more than {them} agreed to move automatically, so they decide. "
                "They see the amount and when it's back — nothing else.",
            )
        if status in ("failed", "declined"):
            why = (
                "The bank didn't accept it, so nothing moved."
                if status == "failed"
                else f"{them} couldn't cover this one, or your agreement changed. Nothing moved."
            )
            return ActivityItem(
                id=b["id"],
                date=when,
                kind="problem",
                title=f"Support from {them} didn't happen",
                amount=amt,
                status="Nothing moved",
                why=why,
            )
        checking = status == "reconcile"
        return ActivityItem(
            id=b["id"],
            date=when,
            kind="received",
            title=f"{them} covered you",
            amount=amt,
            status="Being confirmed with the bank"
            if checking
            else f"With you · expected back after {_wmd(b.get('due_date'))}",
            why=(
                "Runway is confirming this transfer with the bank. Nothing will be sent twice."
                if checking
                else f"Runway covered part of a gap before your payday using the support you agreed with {them}. "
                "It goes back automatically after your next verified payday — only when that's safe for you."
            ),
            reference=ref,
        )
    # support I provided
    them = b["borrower_name"]
    ref = b.get("back_deposit_id") if status == "repaid" else b.get("out_transfer_id")
    if status == "repaid":
        return ActivityItem(
            id=b["id"],
            date=when,
            kind="repaid_to_me",
            title=f"{them} paid you back",
            amount=amt,
            status="Back with you",
            why="Paid back after their verified payday.",
            reference=ref,
        )
    if status == "pending_approval":
        return ActivityItem(
            id=b["id"],
            date=when,
            kind="pending_my_ok",
            title=f"{them} could use {_money(amt)}",
            amount=amt,
            status="Your call",
            why="It's over what you agreed Runway may move automatically, so it waits for you. "
            "Approve or decline in Circles.",
        )
    if status in ("failed", "declined"):
        return ActivityItem(
            id=b["id"],
            date=when,
            kind="problem",
            title=f"Support for {them} didn't happen",
            amount=amt,
            status="Nothing moved",
            why="It was declined, the agreement changed, or the bank didn't accept it. Nothing moved.",
        )
    checking = status == "reconcile"
    limit = f"your {_money(my_limit)} limit" if my_limit else "your limit"
    return ActivityItem(
        id=b["id"],
        date=when,
        kind="provided",
        title=f"You covered {them}",
        amount=amt,
        status="Being confirmed with the bank" if checking else f"Expected back {_wmd(b.get('due_date'))}",
        why=(
            "Runway is confirming this transfer with the bank. Nothing will be sent twice."
            if checking
            else f"Runway provided {_money(amt)} under your support agreement with {them}. It was within "
            f"{limit}, and your own forecast stayed above the {_money(my_floor)} you keep until it's expected back."
        ),
        reference=ref,
    )


def _bridge_items(b: dict, viewer: str, *, my_limit: float | None, my_floor: float) -> list[ActivityItem]:
    """A bridge is a story in two parts: the help (when it was sent) and, later, the repayment. Both stay
    in the timeline — the original help never disappears once it's paid back."""
    if b["status"] != "repaid":
        return [item(b, viewer, my_limit=my_limit, my_floor=my_floor)]
    sent = item({**b, "status": "active", "repaid_at": None}, viewer, my_limit=my_limit, my_floor=my_floor)
    sent = sent.model_copy(update={"id": f"{b['id']}:out", "status": "Paid back"})
    back = item(b, viewer, my_limit=my_limit, my_floor=my_floor).model_copy(update={"id": f"{b['id']}:back"})
    return [sent, back]


def people_items(viewer: str, payments: list[dict], requests: list[dict]) -> list[ActivityItem]:
    """Money sent and asked for between people in your circles — amounts and notes only."""
    out = []
    for p in payments:
        mine = p["from_slug"] == viewer
        them = p["to_name"] if mine else p["from_name"]
        out.append(
            ActivityItem(
                id=p["id"],
                date=_day(p["ts"]) or date.today(),
                kind="sent" if mine else "got",
                title=f"You sent {them} {_money(float(p['amount']))}"
                if mine
                else f"{them} sent you {_money(float(p['amount']))}",
                amount=float(p["amount"]),
                status=p["memo"],
                why=(
                    f"A real transfer from your checking to {them}'s. They see the amount and your note — nothing else."
                    if mine
                    else f"{them} sent this to you. Only the amount and their note are shared."
                ),
                reference=p.get("transfer_id") if mine else p.get("deposit_id"),
            )
        )
    for r in requests:
        if r["status"] == "paid":
            continue  # the payment itself is already in the timeline
        asked_by_me = r["from_slug"] == viewer
        them = r["to_name"] if asked_by_me else r["from_name"]
        word = {
            "open": "Waiting",
            "settling": "Paying…",
            "declined": "Declined",
            "cancelled": "Cancelled",
            "failed": "Being checked",
        }
        out.append(
            ActivityItem(
                id=r["id"],
                date=_day(r["created_at"]) or date.today(),
                kind="asked" if asked_by_me else "asked_you",
                title=f"You asked {them} for {_money(float(r['amount']))}"
                if asked_by_me
                else f"{them} asked you for {_money(float(r['amount']))}",
                amount=float(r["amount"]),
                status=f"{word.get(r['status'], r['status'])} · {r['memo']}",
                why=(
                    "Nothing moves until they pay it from their own account. They see only the amount and your note."
                    if asked_by_me
                    else "Pay or decline it in Circles. Paying moves money from your own account."
                ),
            )
        )
    return out


def feed(
    viewer: str,
    bridges: list[dict],
    limits: dict[str, float],
    my_floor: float,
    payments: list[dict] = (),
    requests: list[dict] = (),
) -> list[ActivityItem]:
    """Everything that involves `viewer`, newest first. `limits`: their current limit per person they support."""
    items = [
        i
        for b in bridges
        if viewer in (b["borrower_slug"], b["lender_slug"])
        for i in _bridge_items(b, viewer, my_limit=limits.get(b["borrower_slug"]), my_floor=my_floor)
    ]
    items += people_items(viewer, list(payments), list(requests))
    return sorted(items, key=lambda i: (i.date, i.id), reverse=True)

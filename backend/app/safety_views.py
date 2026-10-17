"""Safety net: database rows → API models, live or demo."""

import logging
from datetime import date, datetime, timedelta

from app.cashflow import LOCAL_TZ
from app.config import get_settings
from app.schemas import (
    Bridge,
    ProjectedLow,
    SafetyDecision,
    SafetyEvent,
    SafetyLimit,
    SafetyNetSummary,
    SupportAgreement,
    SupportSummary,
)

log = logging.getLogger(__name__)


def _day(ts: datetime | None) -> date | None:
    return ts.astimezone(LOCAL_TZ).date() if ts else None


def bridge(row: dict) -> Bridge:
    return Bridge(
        id=row["id"],
        borrower=row["borrower_slug"],
        borrower_name=row["borrower_name"],
        lender=row["lender_slug"],
        lender_name=row["lender_name"],
        amount=float(row["amount"]),
        reason=row["reason"],
        status=row["status"],
        mode=row["mode"],
        approval_channel=row["approval_channel"],
        shortfall_date=row["shortfall_date"],
        due_date=row["due_date"],
        created=_day(row["created_at"]),
        funded_on=_day(row["funded_at"]),
        repaid_on=_day(row["repaid_at"]),
    )


def for_lender(b: Bridge) -> Bridge:
    """The bridge as the person covering it sees it: who, how much, and when it comes back — never
    the borrower's balance, spending, or what it was for. People told us the embarrassment of family
    seeing their money is why they'd leave the safety net off, so the stored reason (which names the
    borrower's projected balance) stays with the borrower."""
    return b.model_copy(update={"reason": f"Covering {b.borrower_name} until payday."})


def limit(row: dict) -> SafetyLimit:
    lim, out = float(row["limit_amount"]), float(row["outstanding"])
    return SafetyLimit(
        lender=row["lender_slug"],
        lender_name=row["lender_name"],
        borrower=row["borrower_slug"],
        borrower_name=row["borrower_name"],
        limit=lim,
        outstanding=out,
        remaining=max(0.0, lim - out),
        enabled=row["enabled"],
    )


def summary(slug: str) -> SafetyNetSummary:
    if not get_settings().live:
        return demo_summary(slug)
    from app import safety_net  # live-only dependency

    s = safety_net.summary(slug)
    return SafetyNetSummary(
        persona=slug,
        next_payday=s["next_payday"],
        projected_low=ProjectedLow(**s["projected_low"]) if s["projected_low"] else None,
        limits_i_set=[limit(r) for r in s["limits_i_set"]],
        limits_for_me=[limit(r) for r in s["limits_for_me"]],
        borrowed=[bridge(r) for r in s["borrowed"]],
        lent=[for_lender(bridge(r)) for r in s["lent"]],
        approvals_waiting=[for_lender(bridge(r)) for r in s["approvals_waiting"]],
        events=[
            SafetyEvent(at=e["at"], kind=e["kind"], message=e["message"], bridge_id=e["bridge_id"]) for e in s["events"]
        ],
    )


def decision(d, bridge_row: dict | None) -> SafetyDecision:
    return SafetyDecision(
        borrower=d.borrower,
        action=d.action,
        reason=d.reason,
        amount=float(d.amount),
        lender=d.lender,
        shortfall_date=d.shortfall_date,
        low_balance=float(d.low_balance) if d.low_balance is not None else None,
        due_date=d.due_date,
        executed=bridge_row is not None,
        bridge=bridge(bridge_row) if bridge_row else None,
    )


# ---------- demo data: every state the UI has to render ----------
NAMES = {"maya": "Maya", "jordan": "Jordan", "sam": "Sam"}


def _demo_bridge(**kw) -> Bridge:
    today = date.today()
    base = dict(
        reason="Maya would drop to $208 on Nov 5, before payday on Nov 6.",
        approval_channel=None,
        created=today,
        funded_on=today,
        repaid_on=None,
        shortfall_date=today + timedelta(days=19),
        due_date=today + timedelta(days=20),
    )
    return Bridge(**{**base, **kw})


def demo_summary(slug: str) -> SafetyNetSummary:
    today, now = date.today(), datetime.now(LOCAL_TZ)
    active = _demo_bridge(
        id="demo-b1",
        borrower="maya",
        borrower_name="Maya",
        lender="sam",
        lender_name="Sam",
        amount=100,
        status="active",
        mode="auto",
    )
    repaid = _demo_bridge(
        id="demo-b0",
        borrower="jordan",
        borrower_name="Jordan",
        lender="sam",
        lender_name="Sam",
        amount=250,
        status="repaid",
        mode="auto",
        reason="Jordan's mortgage landed before payday.",
        created=today - timedelta(days=16),
        funded_on=today - timedelta(days=16),
        shortfall_date=today - timedelta(days=15),
        due_date=today - timedelta(days=3),
        repaid_on=today - timedelta(days=3),
    )
    pending = _demo_bridge(
        id="demo-b2",
        borrower="maya",
        borrower_name="Maya",
        lender="jordan",
        lender_name="Jordan",
        amount=150,
        status="pending_approval",
        mode="approval",
        funded_on=None,
        approval_channel="auth0_push",
        reason="$150 is over Jordan's auto limit ($50 left).",
    )
    limits = [
        SafetyLimit(
            lender="sam",
            lender_name="Sam",
            borrower="maya",
            borrower_name="Maya",
            limit=100,
            outstanding=100,
            remaining=0,
            enabled=True,
        ),
        SafetyLimit(
            lender="sam",
            lender_name="Sam",
            borrower="jordan",
            borrower_name="Jordan",
            limit=300,
            outstanding=0,
            remaining=300,
            enabled=True,
        ),
        SafetyLimit(
            lender="jordan",
            lender_name="Jordan",
            borrower="maya",
            borrower_name="Maya",
            limit=50,
            outstanding=0,
            remaining=50,
            enabled=True,
        ),
    ]
    ev = {
        "maya": [
            SafetyEvent(
                at=now,
                kind="bridge_auto",
                bridge_id="demo-b1",
                message="🛟 Sam covered you with $100 before Nov 5 — it goes back automatically on payday.",
            )
        ],
        "sam": [
            SafetyEvent(
                at=now,
                kind="bridge_auto",
                bridge_id="demo-b1",
                message="🛟 Runway sent $100 of yours to Maya (within your limit). You get it back on payday.",
            ),
            SafetyEvent(
                at=now - timedelta(days=3),
                kind="repaid",
                bridge_id="demo-b0",
                message="💸 You got your $250 back from Jordan.",
            ),
        ],
        "jordan": [
            SafetyEvent(
                at=now,
                kind="approval_needed",
                bridge_id="demo-b2",
                message="🔔 Maya needs $150 (over your auto limit). Approve — it comes back on payday.",
            )
        ],
    }
    mine = [b for b in (active, repaid, pending) if slug in (b.borrower, b.lender)]
    return SafetyNetSummary(
        persona=slug,
        next_payday=today + timedelta(days=20),
        projected_low=ProjectedLow(date=today + timedelta(days=19), balance=208.0) if slug == "maya" else None,
        limits_i_set=[x for x in limits if x.lender == slug],
        limits_for_me=[x for x in limits if x.borrower == slug],
        borrowed=[b for b in mine if b.borrower == slug],
        lent=[for_lender(b) for b in mine if b.lender == slug and b.status != "pending_approval"],
        approvals_waiting=[for_lender(b) for b in mine if b.lender == slug and b.status == "pending_approval"],
        events=ev.get(slug, []),
    )


# ---------- Quiet Support Agreements ----------
def agreement(row: dict, viewer: str) -> SupportAgreement:
    """An agreement row as `viewer` (one of the two people) may see it."""
    from app import agreements

    mine = "supporter" if row["supporter"] == viewer else "recipient"
    theirs = "recipient" if mine == "supporter" else "supporter"
    return SupportAgreement(
        supporter=row["supporter"],
        supporter_name=row["supporter_name"],
        recipient=row["recipient"],
        recipient_name=row["recipient_name"],
        my_side=mine,
        state=agreements.state(row),
        i_agreed=row[f"{mine}_consent_at"] is not None,
        they_agreed=row[f"{theirs}_consent_at"] is not None,
        limit=float(row["limit_amount"]) if row.get("limit_amount") is not None else None,
        outstanding=float(row["outstanding"]),
        version=row["version"],
    )


def support_summary(viewer: str, rows: list[dict]) -> SupportSummary:
    mine = [agreement(r, viewer) for r in rows if viewer in (r["supporter"], r["recipient"])]
    return SupportSummary(
        persona=viewer,
        supporting=[a for a in mine if a.my_side == "supporter"],
        supporters=[a for a in mine if a.my_side == "recipient"],
    )


def demo_support(viewer: str) -> SupportSummary:
    """Offline/demo mode: the scripted relationships, both sides agreed."""
    from seed.personas import PERSONAS, SAFETY_LIMITS

    names = {p.slug: p.first_name for p in PERSONAS}
    rows = [
        {
            "supporter": s,
            "supporter_name": names[s],
            "recipient": r,
            "recipient_name": names[r],
            "supporter_consent_at": "demo",
            "recipient_consent_at": "demo",
            "revoked_at": None,
            "limit_amount": amount,
            "enabled": True,
            "outstanding": 0,
            "version": 1,
        }
        for s, r, amount in SAFETY_LIMITS
    ]
    return support_summary(viewer, rows)


def support_for(viewer: str) -> SupportSummary:
    """`viewer`'s own agreements, live or demo — the one place the API and the assistant both read."""
    if not get_settings().live:
        return demo_support(viewer)
    from app.db import agreements_repo, pool

    with pool.connection() as conn:
        return support_summary(viewer, agreements_repo.involving(conn, viewer))

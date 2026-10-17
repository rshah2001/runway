"""Family safety net — an agent that acts on your behalf so you never have to ask for money.

Each family member (the LENDER) sets how much the agent may move from them to someone else without
asking, as long as it comes back by the borrower's next payday. When a borrower's forecast dips
under the safety floor before payday, the agent picks the family member with the most runway for
whom helping is also safe, then:
  * under that lender's limit → moves the money automatically and tells both of them
  * over the limit            → sends the lender an Auth0 push to approve (in-app fallback)
On payday it repays the lender automatically and tells them their money is back.

`decide()` is pure: every guardrail is here and unit-tested. Everything else moves real money in
Nessie (only with LIVE_TRANSFERS=1) and claims each bridge with an atomic status update first, so a
bridge can never be funded or repaid twice.
"""

import logging
import math
import secrets
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal

from app import auth0_ciba
from app.cashflow import LOCAL_TZ, Projection, project
from app.config import get_settings
from app.db import pool, repo, safety_repo
from app.ingest import sync_customer
from app.nessie.client import NessieClient
from app.nessie.moves import TransferNotMade, move_money

log = logging.getLogger(__name__)

SAFE_FLOOR = Decimal("300")  # same floor as the forecast engine
ROUND_TO = 10  # bridges are whole tens: a $92.18 gap becomes a $100 bridge
MAX_BRIDGE = Decimal("1000")
MAX_DAYS_TO_PAYDAY = 31  # "it comes back" means by the next payday, and that must be soon
REPAY_GRACE_DAYS = 3  # after this many days past due without enough money, the bridge is flagged

Action = Literal["none", "auto_bridge", "needs_approval", "no_safe_helper", "no_payday", "already_covered"]


@dataclass(frozen=True)
class Helper:
    projection: Projection
    limit: Decimal  # set by this lender for this borrower
    outstanding: Decimal  # already lent to this borrower and not yet back
    enabled: bool
    is_borrowing: bool  # someone who owes money right now never lends (no chains)

    @property
    def remaining(self) -> Decimal:
        return max(Decimal(0), self.limit - self.outstanding)


@dataclass(frozen=True)
class Decision:
    borrower: str
    action: Action
    reason: str
    amount: Decimal = Decimal(0)
    lender: str | None = None
    shortfall_date: date | None = None
    low_balance: Decimal | None = None
    due_date: date | None = None


def _md(d: date) -> str:
    return f"{d:%b} {d.day}"  # "Oct 22" — portable; %-d is glibc-only and crashes on Windows


def _wmd(d: date) -> str:
    return f"{d:%a %b} {d.day}"  # "Fri Oct 23"


def _money(x: Decimal) -> str:
    return f"${x:,.2f}".replace(".00", "")


def decide(
    b: Projection, helpers: list[Helper], today: date, *, has_open_bridge: bool = False, floor: Decimal = SAFE_FLOOR
) -> Decision:
    """What the agent should do for borrower `b` today. Pure — no I/O."""
    name = b.first_name
    if has_open_bridge:
        return Decision(b.slug, "already_covered", f"{name} already has a bridge in progress.")
    if b.next_payday is None or (b.next_payday - today).days > MAX_DAYS_TO_PAYDAY:
        return Decision(
            b.slug, "no_payday", f"No payday within {MAX_DAYS_TO_PAYDAY} days — a bridge couldn't come back."
        )

    low = b.low(today, b.next_payday)  # the gap before payday
    if low is None or low[1] >= floor:
        return Decision(b.slug, "none", f"{name} stays above {_money(floor)} until payday.")
    short_day, short_bal = low
    need = Decimal(math.ceil((floor - short_bal) / ROUND_TO) * ROUND_TO)
    base = dict(shortfall_date=short_day, low_balance=short_bal, due_date=b.next_payday)
    gap = f"{name} would drop to {_money(short_bal)} on {_md(short_day)}, before payday on {_md(b.next_payday)}"

    if need > MAX_BRIDGE:
        return Decision(b.slug, "no_safe_helper", f"{gap} — the gap is bigger than any bridge.", need, **base)
    after_payday = b.low(b.next_payday, b.next_payday + timedelta(days=4))
    if after_payday and after_payday[1] < floor:
        reason = f"{gap}, but repaying on payday would leave {name} under {_money(floor)} — not a safe bridge."
        return Decision(b.slug, "no_safe_helper", reason, need, **base)

    safe = []
    for h in helpers:
        if not h.enabled or h.is_borrowing:
            continue
        h_low = h.projection.low(today, b.next_payday + timedelta(days=1))
        if h_low is not None and h_low[1] - need >= floor:  # helping must keep the helper safe too
            safe.append((h, h_low[1]))
    if not safe:
        return Decision(b.slug, "no_safe_helper", f"{gap}. Nobody in the family can cover it safely.", need, **base)

    safe.sort(key=lambda x: x[1], reverse=True)  # most runway first
    under = [h for h, _ in safe if h.remaining >= need]
    if under:
        h = under[0]
        reason = (
            f"{gap}. {h.projection.first_name} covers {_money(need)} within their {_money(h.limit)} limit "
            f"and stays safe; it comes back on {_md(b.next_payday)}."
        )
        return Decision(b.slug, "auto_bridge", reason, need, h.projection.slug, **base)
    h = safe[0][0]
    reason = (
        f"{gap}. {_money(need)} is over {h.projection.first_name}'s auto limit "
        f"({_money(h.remaining)} left), so they need to approve it."
    )
    return Decision(b.slug, "needs_approval", reason, need, h.projection.slug, **base)


# ---------------------------------------------------------------------------------------------
# Live side: gather inputs, act on decisions, repay, approvals. Real money only with LIVE_TRANSFERS.
# ---------------------------------------------------------------------------------------------
_lock = threading.Lock()  # one safety-net pass at a time within this process


def writes_enabled() -> bool:
    s = get_settings()
    return s.live and s.live_transfers


def _today() -> date:
    return datetime.now(LOCAL_TZ).date()


def plan(conn, borrower_slug: str, today: date | None = None) -> Decision:
    today = today or _today()
    slugs = [p["slug"] for p in repo.personas(conn)]
    projections = {s: project(conn, s, today) for s in slugs}
    owing = {b["borrower_slug"] for b in safety_repo.outstanding_bridges(conn)}
    helpers = [
        Helper(
            projection=projections[lim["lender_slug"]],
            limit=Decimal(lim["limit_amount"]),
            outstanding=Decimal(lim["outstanding"]),
            enabled=lim["enabled"],
            is_borrowing=lim["lender_slug"] in owing,
        )
        for lim in safety_repo.limits(conn, borrower=borrower_slug)
    ]
    has_open = safety_repo.open_bridge_for_borrower(conn, borrower_slug) is not None
    return decide(projections[borrower_slug], helpers, today, has_open_bridge=has_open)


def _both(conn, b: dict, kind: str, to_borrower: str, to_lender: str) -> None:
    safety_repo.add_event(conn, b["borrower_slug"], kind, to_borrower, b["id"])
    safety_repo.add_event(conn, b["lender_slug"], kind, to_lender, b["id"])


def _move(lender: dict, borrower: dict, amount: float, memo: str, deposit_memo: str) -> tuple[str, str]:
    nessie = NessieClient.from_settings()
    ids = move_money(nessie, lender["checking_id"], borrower["checking_id"], amount, _today(), memo, deposit_memo)
    try:  # balances refresh now; if this fails the background sync catches up
        with pool.connection() as conn:
            for p in (lender, borrower):
                sync_customer(conn, nessie, p["customer_id"])
            conn.commit()
    except Exception:
        log.exception("money moved, re-sync failed")
    return ids


def _fund(bridge_id: str) -> dict | None:
    """Move the bridge's money lender → borrower. Only one caller can claim a bridge."""
    with pool.connection() as conn:
        b = safety_repo.transition(conn, bridge_id, ("pending_approval",), "funding")
        conn.commit()
        if b is None:
            return None
        lender, borrower = repo.persona(conn, b["lender_slug"]), repo.persona(conn, b["borrower_slug"])
    amount = float(b["amount"])
    try:
        t_id, d_id = _move(
            lender, borrower, amount, f"Safety net for {b['borrower_name']}", f"From {b['lender_name']} (safety net)"
        )
    except Exception as e:
        nothing_moved = isinstance(e, TransferNotMade)
        with pool.connection() as conn:
            safety_repo.transition(conn, bridge_id, ("funding",), "failed")
            note = "nothing moved" if nothing_moved else "we're checking with the bank"
            _both(
                conn,
                b,
                "bridge_failed",
                f"The bridge from {b['lender_name']} didn't go through — {note}.",
                f"Your bridge to {b['borrower_name']} didn't go through — {note}.",
            )
            conn.commit()
        log.exception("bridge %s funding failed", bridge_id)
        return None
    with pool.connection() as conn:
        b = safety_repo.transition(
            conn,
            bridge_id,
            ("funding",),
            "active",
            funded_at=datetime.now(LOCAL_TZ),
            out_transfer_id=t_id,
            out_deposit_id=d_id,
        )
        due = f"{_wmd(b['due_date'])}"
        if b["mode"] == "auto":
            _both(
                conn,
                b,
                "bridge_auto",
                f"🛟 {b['lender_name']} covered you with ${amount:,.0f} before {_md(b['shortfall_date'])} — "
                f"it goes back automatically on payday, {due}.",
                f"🛟 Runway sent ${amount:,.0f} of yours to {b['borrower_name']} (within your limit). "
                f"You get it back on {due}.",
            )
        else:
            _both(
                conn,
                b,
                "bridge_approved",
                f"✅ {b['lender_name']} approved ${amount:,.0f} — it goes back automatically on {due}.",
                f"✅ You sent ${amount:,.0f} to {b['borrower_name']}. You get it back on {due}.",
            )
        conn.commit()
    return b


def _request_approval(conn, b: dict) -> str:
    """Ask the lender: Auth0 push when configured, otherwise an in-app approval card."""
    cfg = auth0_ciba.config()
    if cfg and b["lender_slug"] in cfg.users:
        try:
            msg = f"Approve {int(b['amount'])} for {b['borrower_name']} back {b['due_date']:%b %d}"
            req_id = auth0_ciba.start(cfg, cfg.users[b["lender_slug"]], msg)
            safety_repo.transition(
                conn,
                b["id"],
                ("pending_approval",),
                "pending_approval",
                approval_channel="auth0_push",
                auth_req_id=req_id,
            )
            return "auth0_push"
        except Exception:
            log.exception("Auth0 push failed for bridge %s — falling back to in-app approval", b["id"])
    safety_repo.transition(conn, b["id"], ("pending_approval",), "pending_approval", approval_channel="in_app")
    return "in_app"


def act(decision: Decision) -> dict | None:
    """Turn an auto_bridge / needs_approval decision into a bridge (and real money if auto)."""
    if decision.action not in ("auto_bridge", "needs_approval"):
        return None
    bridge_id = f"bridge-{secrets.token_hex(6)}"
    with pool.connection() as conn:
        if safety_repo.open_bridge_for_borrower(conn, decision.borrower):  # re-check under the lock
            return None
        safety_repo.insert_bridge(
            conn,
            {
                "id": bridge_id,
                "borrower_slug": decision.borrower,
                "lender_slug": decision.lender,
                "amount": decision.amount,
                "reason": decision.reason,
                "status": "pending_approval",
                "mode": "auto" if decision.action == "auto_bridge" else "approval",
                "shortfall_date": decision.shortfall_date,
                "due_date": decision.due_date,
                "approval_channel": None,
            },
        )
        b = safety_repo.bridge(conn, bridge_id)
        if decision.action == "needs_approval":
            channel = _request_approval(conn, b)
            where = "on your phone" if channel == "auth0_push" else "in Runway"
            _both(
                conn,
                b,
                "approval_needed",
                f"Asked {b['lender_name']} to approve ${decision.amount:,.0f} — it's over their auto limit.",
                f"🔔 {b['borrower_name']} needs ${decision.amount:,.0f} before {_md(decision.shortfall_date)} "
                f"(over your auto limit). Approve {where} — it comes back {_md(decision.due_date)}.",
            )
        conn.commit()
    return _fund(bridge_id) if decision.action == "auto_bridge" else b


def approve(bridge_id: str) -> dict | None:
    """The lender approved (in-app, or via the Auth0 push)."""
    return _fund(bridge_id)


def decline(bridge_id: str) -> dict | None:
    with pool.connection() as conn:
        b = safety_repo.transition(conn, bridge_id, ("pending_approval",), "declined")
        if b:
            _both(
                conn,
                b,
                "bridge_declined",
                f"{b['lender_name']} couldn't cover this one.",
                f"You declined {b['borrower_name']}'s bridge.",
            )
        conn.commit()
    return b


def repay_due(today: date | None = None) -> list[dict]:
    """On (or after) the due date, pay each lender back — but never push the borrower under the floor."""
    today, done = today or _today(), []
    with pool.connection() as conn:
        due = [b for b in safety_repo.outstanding_bridges(conn) if b["due_date"] <= today and b["status"] != "repaying"]
    for b in due:
        with pool.connection() as conn:
            borrower, lender = repo.persona(conn, b["borrower_slug"]), repo.persona(conn, b["lender_slug"])
            bal = next(
                Decimal(a["balance"])
                for a in repo.accounts_with_balances(conn, borrower["customer_id"])
                if a["id"] == borrower["checking_id"]
            )
            if bal - Decimal(b["amount"]) < SAFE_FLOOR:  # paycheck not in yet: wait
                if (today - b["due_date"]).days >= REPAY_GRACE_DAYS and b["status"] == "active":
                    safety_repo.transition(conn, b["id"], ("active",), "repay_failed")
                    _both(
                        conn,
                        b,
                        "repay_late",
                        f"Your ${b['amount']:,.0f} repayment to {b['lender_name']} is waiting for your paycheck.",
                        f"{b['borrower_name']}'s ${b['amount']:,.0f} repayment is late — "
                        "no new bridges until it's back.",
                    )
                    conn.commit()
                continue
            claimed = safety_repo.transition(conn, b["id"], ("active", "repay_failed"), "repaying")
            conn.commit()
        if claimed is None:
            continue
        amount = float(b["amount"])
        try:
            t_id, d_id = _move(
                borrower,
                lender,
                amount,
                f"Safety net repayment to {b['lender_name']}",
                f"Repaid by {b['borrower_name']} (safety net)",
            )
        except Exception:
            log.exception("repayment of %s failed", b["id"])
            with pool.connection() as conn:
                safety_repo.transition(conn, b["id"], ("repaying",), "repay_failed")
                conn.commit()
            continue
        with pool.connection() as conn:
            row = safety_repo.transition(
                conn,
                b["id"],
                ("repaying",),
                "repaid",
                repaid_at=datetime.now(LOCAL_TZ),
                back_transfer_id=t_id,
                back_deposit_id=d_id,
            )
            _both(
                conn,
                b,
                "repaid",
                f"✅ Repaid {b['lender_name']} ${amount:,.0f} from your paycheck.",
                f"💸 You got your ${amount:,.0f} back from {b['borrower_name']}.",
            )
            conn.commit()
        done.append(row)
    return done


def poll_push_approvals() -> None:
    """Check Auth0 for answers to outstanding push approvals."""
    cfg = auth0_ciba.config()
    if not cfg:
        return
    with pool.connection() as conn:
        waiting = [b for b in safety_repo.pending_approvals(conn) if b["auth_req_id"]]
    for b in waiting:
        try:
            answer = auth0_ciba.poll(cfg, b["auth_req_id"])
        except Exception:
            log.exception("Auth0 poll failed for %s", b["id"])
            continue
        if answer == "approved":
            approve(b["id"])
        elif answer in ("denied", "expired"):
            decline(b["id"])


def run(slugs: list[str] | None = None) -> list[tuple[Decision, dict | None]]:
    """Plan for each borrower and act on it — but only act when real writes are on; otherwise this
    is a dry run that reports what the agent *would* do."""
    out = []
    with _lock:
        with pool.connection() as conn:
            targets = slugs or [p["slug"] for p in repo.personas(conn)]
        for slug in targets:
            try:
                with pool.connection() as conn:
                    decision = plan(conn, slug)
                out.append((decision, act(decision) if writes_enabled() else None))
            except Exception:
                log.exception("safety net pass failed for %s", slug)
    return out


def tick() -> None:
    """One full pass, after every background sync — only when real writes are on."""
    if not writes_enabled():
        return
    poll_push_approvals()
    repay_due()
    run()


def summary(slug: str) -> dict:
    """Everything one person's safety-net screen needs, from their point of view."""
    with pool.connection() as conn:
        if repo.persona(conn, slug) is None:
            raise LookupError(slug)
        p = project(conn, slug)
        bridges = safety_repo.bridges_for(conn, slug)
        low = p.low(_today(), p.next_payday) if p.next_payday else None
        return {
            "persona": slug,
            "next_payday": p.next_payday,
            "projected_low": {"date": low[0], "balance": float(low[1])} if low else None,
            "limits_i_set": safety_repo.limits(conn, lender=slug),
            "limits_for_me": safety_repo.limits(conn, borrower=slug),
            "borrowed": [b for b in bridges if b["borrower_slug"] == slug],
            "lent": [b for b in bridges if b["lender_slug"] == slug],
            "approvals_waiting": safety_repo.pending_approvals(conn, lender=slug),
            "events": safety_repo.events(conn, slug),
        }

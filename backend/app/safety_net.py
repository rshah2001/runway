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

import dataclasses
import logging
import secrets
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal

import psycopg

from app import agreements, auth0_ciba, guardian, prefs, reconcile
from app.cashflow import LOCAL_TZ, Projection, project
from app.config import get_settings
from app.db import agreements_repo, journal_repo, pool, repo, safety_repo
from app.ingest import sync_customer
from app.nessie.client import NessieClient
from app.nessie.moves import TransferNotMade, move_money

log = logging.getLogger(__name__)

SAFE_FLOOR = Decimal("300")  # the default floor; each person can set their own (app/prefs.py)
REPAY_CHECK_DAYS = 7  # repaying must not cause a new predicted shortfall in the week after payday
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
    exposure_remaining: Decimal = guardian.DEFAULT_EXPOSURE  # their total cap across everyone, minus what's out
    automatic: bool = True  # False: this supporter asked to approve every time ('approval' mode)

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
    floor: Decimal | None = None  # the borrower's floor this decision used (kept on the bridge)
    allocations: tuple[tuple[str, Decimal], ...] = ()  # (supporter, amount): one bridge each
    versions: tuple[tuple[str, int], ...] = ()  # the consent each share relied on; re-checked before money moves
    # supporters who agreed but were kept out because helping wasn't safe for THEM: (slug, their cushion, why).
    # Logged for the audit trail only — never sent to them, since its timing would reveal someone's shortfall.
    held: tuple[tuple[str, Decimal, str], ...] = ()


def _md(d: date) -> str:
    return f"{d:%b} {d.day}"  # "Oct 22" — portable; %-d is glibc-only and crashes on Windows


def _wmd(d: date) -> str:
    return f"{d:%a %b} {d.day}"  # "Fri Oct 23"


def _money(x: Decimal) -> str:
    return f"${x:,.2f}".replace(".00", "")


def _capacity(h: Helper, today: date, end: date) -> guardian.Capacity:
    """A supporter's safe room; nothing automatic if they asked to approve every time."""
    cap = guardian.capacity(
        h.projection.days_low or h.projection.days,
        h.projection.floor,
        start=today,
        end=end,
        pair_remaining=h.remaining,
        exposure_remaining=h.exposure_remaining,
        confident=h.projection.confident,
    )
    return cap if h.automatic else guardian.Capacity(Decimal(0), "approval_only", cap.cash_room)


def decide(
    b: Projection,
    helpers: list[Helper],
    today: date,
    *,
    has_open_bridge: bool = False,
    floor: Decimal | None = None,
    owe_room: Decimal | None = None,
    allow_multi: bool = True,
) -> Decision:
    """What the agent should do for borrower `b` today. Pure — no I/O.

    Everyone is measured against their own floor (what they keep in checking): the borrower's says
    whether there's a dip and how much it takes; each helper's says whether helping keeps *them* safe.
    `floor` overrides the borrower's (tests)."""
    floor = b.floor if floor is None else floor
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
    need = guardian.round_up(floor - short_bal)
    base = dict(shortfall_date=short_day, low_balance=short_bal, due_date=b.next_payday, floor=floor)
    gap = f"{name} would drop to {_money(short_bal)} on {_md(short_day)}, before payday on {_md(b.next_payday)}"

    if need > MAX_BRIDGE:
        return Decision(b.slug, "no_safe_helper", f"{gap} — the gap is bigger than any bridge.", need, **base)
    # the recipient's own cap on what they'll owe at once (their setting, their side only)
    if owe_room is not None and need > owe_room:
        reason = f"{gap}, but that's more than the {_money(max(Decimal(0), owe_room))} more you said you'd owe at once."
        return Decision(b.slug, "no_safe_helper", reason, need, **base)
    # repaying on payday must not just move the shortfall a few days later
    after_payday = b.low(b.next_payday, b.next_payday + timedelta(days=REPAY_CHECK_DAYS))
    if after_payday and after_payday[1] - need < floor:
        reason = (
            f"{gap}, but repaying {_money(need)} on payday would leave {name} under {_money(floor)} "
            "— that would only move the shortfall, so it isn't a safe bridge."
        )
        return Decision(b.slug, "no_safe_helper", reason, need, **base)

    # Network Guardian: each supporter's SAFE room over the whole time the money is out
    end = b.next_payday + timedelta(days=REPAY_GRACE_DAYS)
    caps = [(h, _capacity(h, today, end)) for h in helpers if h.enabled and not h.is_borrowing]
    names = {h.projection.slug: h.projection.first_name for h, _ in caps}
    held = tuple(
        (h.projection.slug, h.projection.floor, c.bound)
        for h, c in caps
        if c.amount == 0 and c.bound in ("cushion", "low_confidence")
    )
    pool_caps = [(h.projection.slug, c) for h, c in caps]
    if not allow_multi:  # the recipient wants one person to cover it, or nobody automatically
        pool_caps = [(s, c) for s, c in pool_caps if c.amount >= need]
    shares = guardian.allocate(need, pool_caps)
    if shares and sum(a for _, a in shares) >= need:
        who = " and ".join(f"{names[s]} covers {_money(a)}" for s, a in shares)
        reason = f"{gap}. {who} — within their limits, with their own bills still covered."
        reason += f" Expected back {_md(b.next_payday)}."
        return Decision(b.slug, "auto_bridge", reason, need, shares[0][0], allocations=tuple(shares), held=held, **base)

    # not enough automatic room: ask ONE person whose own cushion allows the whole amount
    approvable = [(h, c) for h, c in caps if c.cash_room >= need]
    if approvable:
        h, _ = max(approvable, key=lambda hc: (hc[1].cash_room, hc[0].projection.slug))
        slug = h.projection.slug
        reason = f"{gap}. {_money(need)} is more than Runway can move automatically,"
        reason += f" so {names[slug]} is asked to approve it."
        return Decision(b.slug, "needs_approval", reason, need, slug, allocations=((slug, need),), **base)
    return Decision(
        b.slug,
        "no_safe_helper",
        f"{gap}. Nobody who agreed to help can cover it without risking their own bills.",
        need,
        **base,
    )


# ---------------------------------------------------------------------------------------------
# Live side: gather inputs, act on decisions, repay, approvals. Real money only with LIVE_TRANSFERS.
# ---------------------------------------------------------------------------------------------
_lock = threading.Lock()  # one safety-net pass at a time within this process
_IN_FLIGHT: set[str] = set()  # journal keys whose Nessie call is running in this process right now
_in_flight_lock = threading.Lock()
# an open journal row untouched this long is past any in-flight Nessie write (30 s timeout, plus
# connect retries ≈ 2 min), so the reconciler may look at it
STUCK_AFTER = timedelta(minutes=10)


def writes_enabled() -> bool:
    s = get_settings()
    return s.live and s.live_transfers


def _today() -> date:
    return datetime.now(LOCAL_TZ).date()


def plan(conn, borrower_slug: str, today: date | None = None) -> Decision:
    today = today or _today()
    slugs = [p["slug"] for p in repo.personas(conn)]
    projections = {s: project(conn, s, today) for s in slugs}
    # the borrower's own switch beats any limit a relative set: strict, because guessing "on" after a
    # failed read would move family money someone turned off
    if not prefs.setting(borrower_slug, "family_cover", conn, strict=True):
        name = projections[borrower_slug].first_name
        return Decision(borrower_slug, "family_off", f"{name} turned family cover off, so nobody is asked.")
    committed = safety_repo.open_bridges(conn)  # incl. approvals still waiting and transfers in flight
    owing = {b["borrower_slug"] for b in committed if b["status"] in safety_repo.OUTSTANDING}
    lent_out: dict[str, Decimal] = {}  # everything a supporter has committed, for their exposure cap
    unfunded: dict[str, Decimal] = {}  # committed but not yet out of their balance: not in the forecast
    for b in committed:
        amount = Decimal(b["amount"])
        lent_out[b["lender_slug"]] = lent_out.get(b["lender_slug"], Decimal(0)) + amount
        if b["status"] in safety_repo.UNFUNDED:
            unfunded[b["lender_slug"]] = unfunded.get(b["lender_slug"], Decimal(0)) + amount
    # only supporters with an ACTIVE agreement (both people said yes) are ever considered
    consented = {
        a["supporter"]: a
        for a in agreements_repo.involving(conn, borrower_slug)
        if a["recipient"] == borrower_slug and agreements.is_active(a)
    }
    helpers = [
        Helper(
            projection=_less(projections[lim["lender_slug"]], unfunded.get(lim["lender_slug"], Decimal(0))),
            limit=Decimal(lim["limit_amount"]),
            outstanding=Decimal(lim["outstanding"]),
            enabled=lim["enabled"],
            is_borrowing=lim["lender_slug"] in owing,
            exposure_remaining=_exposure_limit(conn, lim["lender_slug"]) - lent_out.get(lim["lender_slug"], Decimal(0)),
            automatic=consented[lim["lender_slug"]].get("mode", "auto") == "auto",
        )
        for lim in safety_repo.limits(conn, borrower=borrower_slug)
        if lim["lender_slug"] in consented
    ]
    has_open = safety_repo.open_bridge_for_borrower(conn, borrower_slug) is not None
    max_owed, allow_multi = repo.receiving(conn, borrower_slug)
    owed_now = sum((Decimal(b["amount"]) for b in committed if b["borrower_slug"] == borrower_slug), Decimal(0))
    owe_room = None if max_owed is None else Decimal(str(max_owed)) - owed_now
    decision = decide(
        projections[borrower_slug], helpers, today, has_open_bridge=has_open, owe_room=owe_room, allow_multi=allow_multi
    )
    versions = tuple((slug, consented[slug]["version"]) for slug, _ in decision.allocations if slug in consented)
    return dataclasses.replace(decision, versions=versions)


def _less(p: Projection, amount: Decimal) -> Projection:
    """A supporter's forecast with money they've already promised (but not yet sent) taken out, so the
    same dollars can't be offered to two people."""
    if not amount:
        return p
    return dataclasses.replace(
        p, days=[(d, bal - amount) for d, bal in p.days], days_low=[(d, bal - amount) for d, bal in p.days_low]
    )


def _exposure_limit(conn, slug: str) -> Decimal:
    """A supporter's total cap across everyone they help (their own setting, or the default)."""
    row = conn.execute("SELECT support_exposure_limit FROM money_preferences WHERE slug = %s", (slug,)).fetchone()
    value = row and list(row.values())[0]
    return Decimal(str(value)) if value is not None else guardian.DEFAULT_EXPOSURE


def _consent_still_holds(conn, lender: str, borrower: str, version: int | None) -> bool:
    """Re-check, under the people's locks, that the agreement a decision relied on is still active and
    unchanged — a revoke, pause or limit change in between means nothing moves."""
    row = agreements_repo.get(conn, lender, borrower)
    return agreements.is_active(row) and version is not None and row["version"] == version


def _both(conn, b: dict, kind: str, to_borrower: str, to_lender: str) -> None:
    safety_repo.add_event(conn, b["borrower_slug"], kind, to_borrower, b["id"])
    safety_repo.add_event(conn, b["lender_slug"], kind, to_lender, b["id"])


def _move(lender: dict, borrower: dict, amount: float, memo: str, deposit_memo: str, *, key: str) -> tuple[str, str]:
    nessie = NessieClient.from_settings()
    with _in_flight_lock:
        _IN_FLIGHT.add(key)
    try:
        ids = move_money(
            nessie, lender["checking_id"], borrower["checking_id"], amount, _today(), memo, deposit_memo, key=key
        )
    finally:
        with _in_flight_lock:
            _IN_FLIGHT.discard(key)
    try:  # balances refresh now; if this fails the background sync catches up
        with pool.connection() as conn:
            for p in (lender, borrower):
                sync_customer(conn, nessie, p["customer_id"])
            conn.commit()
    except Exception:
        log.exception("money moved, re-sync failed")
    return ids


def _fund(bridge_id: str) -> dict | None:
    """Move the bridge's money lender → borrower. Only one caller can claim a bridge, and the journal
    row is written in the same transaction as the claim, before any money moves."""
    with pool.connection() as conn:
        current = safety_repo.bridge(conn, bridge_id)
        if current is None:
            return None
        safety_repo.lock_people(conn, current["lender_slug"], current["borrower_slug"])
        b = safety_repo.transition(conn, bridge_id, ("pending_approval",), "funding")
        if b is None:
            conn.rollback()
            return None
        # the borrower may have turned family cover off while this waited for the lender's answer:
        # their switch wins. A failed read leaves the bridge waiting (rollback) — never a guessed "on".
        try:
            covered = prefs.setting(b["borrower_slug"], "family_cover", conn, strict=True)
        except Exception:
            conn.rollback()
            raise
        if covered and not _consent_still_holds(conn, b["lender_slug"], b["borrower_slug"], b.get("agreement_version")):
            safety_repo.transition(conn, bridge_id, ("funding",), "declined")
            _both(
                conn,
                b,
                "bridge_declined",
                "Your support agreement changed, so nothing was moved.",
                f"Your support agreement with {b['borrower_name']} changed, so nothing was moved.",
            )
            conn.commit()
            return None
        if not covered:
            safety_repo.transition(conn, bridge_id, ("funding",), "declined")
            _both(
                conn,
                b,
                "bridge_declined",
                "You turned family cover off, so nothing was moved.",
                f"{b['borrower_name']} doesn't need this one anymore. Nothing was moved.",
            )
            conn.commit()
            return None
        lender, borrower = repo.persona(conn, b["lender_slug"]), repo.persona(conn, b["borrower_slug"])
        key = f"fund:{bridge_id}"
        amount = float(b["amount"])
        if not journal_repo.claim(conn, key, "fund", bridge_id, lender["checking_id"], borrower["checking_id"], amount):
            conn.rollback()  # this bridge was sent before: never send it again
            log.error("bridge %s already has a funding journal entry; not sending again", bridge_id)
            return None
        conn.commit()
    try:
        t_id, d_id = _move(
            lender,
            borrower,
            amount,
            f"Safety net for {b['borrower_name']}",
            f"From {b['lender_name']} (safety net)",
            key=key,
        )
    except TransferNotMade as e:
        with pool.connection() as conn:
            journal_repo.finish(conn, key, "not_made", error=str(e))
            safety_repo.transition(conn, bridge_id, ("funding",), "failed")
            _both(
                conn,
                b,
                "bridge_failed",
                f"The support from {b['lender_name']} didn't go through — nothing moved.",
                f"Your support for {b['borrower_name']} didn't go through — nothing moved.",
            )
            conn.commit()
        log.warning("bridge %s funding not made: %s", bridge_id, e)
        return None
    except Exception as e:  # unclear outcome: reconcile against Nessie, never retry
        with pool.connection() as conn:
            journal_repo.finish(conn, key, "unknown", error=str(e))
            safety_repo.transition(conn, bridge_id, ("funding",), "reconcile")
            _both(conn, b, "bridge_checking", CHECKING_WITH_BANK, CHECKING_WITH_BANK)
            conn.commit()
        log.exception("bridge %s funding outcome unknown — reconciling", bridge_id)
        return None
    with pool.connection() as conn:
        journal_repo.finish(conn, key, "succeeded", transfer_id=t_id, deposit_id=d_id)
        b = _funded(conn, bridge_id, ("funding",), t_id, d_id)
        conn.commit()
    return b


CHECKING_WITH_BANK = "We're confirming a transfer with the bank. Nothing will be sent twice."


def _funded(conn, bridge_id: str, frm: tuple[str, ...], t_id: str, d_id: str) -> dict | None:
    """Mark a bridge funded (after a confirmed move) and tell both people."""
    b = safety_repo.transition(
        conn, bridge_id, frm, "active", funded_at=datetime.now(LOCAL_TZ), out_transfer_id=t_id, out_deposit_id=d_id
    )
    if b is None:
        return None
    amount, due = float(b["amount"]), _wmd(b["due_date"])
    if b["mode"] == "auto":
        _both(
            conn,
            b,
            "bridge_auto",
            f"🛟 {b['lender_name']} covered you with ${amount:,.0f} before {_md(b['shortfall_date'])} — "
            f"it goes back automatically after your next verified payday ({due}).",
            f"🛟 Your approved safety net sent ${amount:,.0f} to {b['borrower_name']} (within your limit). "
            f"Expected back {due}.",
        )
    else:
        _both(
            conn,
            b,
            "bridge_approved",
            f"✅ {b['lender_name']} approved ${amount:,.0f} — it goes back after your next payday ({due}).",
            f"✅ You sent ${amount:,.0f} to {b['borrower_name']}. Expected back {due}.",
        )
    return b


def _request_approval(conn, b: dict) -> str:
    """Ask the lender: Auth0 push when configured, otherwise an in-app approval card."""
    cfg = auth0_ciba.config()
    if cfg and b["lender_slug"] in cfg.users:
        try:
            msg = f"Approve {int(b['amount'])} support for {b['borrower_name']}"  # lock-screen safe: no dates
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


def _still_safe(conn, lender: str, borrower: str, amount: Decimal, auto: bool, version: int | None) -> bool:
    """Re-validate one share under the people's locks, from fresh rows: the agreement is still active and
    unchanged, the supporter isn't borrowing, and the share still fits their pair limit (automatic only)
    and their total exposure. The forecast-based cash room was computed moments ago in plan()."""
    if not _consent_still_holds(conn, lender, borrower, version):
        return False
    committed = safety_repo.open_bridges(conn)  # incl. approvals waiting and transfers in flight
    if any(b["borrower_slug"] == lender for b in committed):  # no chains: a borrower never lends
        return False
    lent = sum((Decimal(b["amount"]) for b in committed if b["lender_slug"] == lender), Decimal(0))
    if lent + amount > _exposure_limit(conn, lender):
        return False
    if auto:
        if agreements_repo.get(conn, lender, borrower).get("mode", "auto") != "auto":  # asked to approve every time
            return False
        lim = next(iter(safety_repo.limits(conn, lender=lender, borrower=borrower)), None)
        if lim is None or not lim["enabled"] or Decimal(lim["limit_amount"]) - Decimal(lim["outstanding"]) < amount:
            return False
    return True


def act(decision: Decision) -> dict | None:
    """Turn an auto_bridge / needs_approval decision into bridges — one per supporter's share, all
    under one decision id — and move the money for automatic ones. Every share is re-validated under
    the borrower's and every supporter's lock first; if any share no longer holds, nothing is created
    (plan() runs again on the next pass with fresh numbers). Returns the first bridge."""
    if decision.action not in ("auto_bridge", "needs_approval"):
        return None
    auto = decision.action == "auto_bridge"
    shares = decision.allocations or ((decision.lender, decision.amount),)
    versions = dict(decision.versions)
    decision_id = f"dec-{secrets.token_hex(6)}"
    ids: list[str] = []
    with pool.connection() as conn:
        safety_repo.lock_people(conn, decision.borrower, *(slug for slug, _ in shares))
        if safety_repo.open_bridge_for_borrower(conn, decision.borrower):  # re-check under the lock
            conn.rollback()
            return None
        if not all(
            _still_safe(conn, slug, decision.borrower, amount, auto, versions.get(slug)) for slug, amount in shares
        ):
            conn.rollback()
            log.info("decision for %s no longer holds under the lock; re-planning next pass", decision.borrower)
            return None
        try:
            for slug, amount in shares:
                bridge_id = f"bridge-{secrets.token_hex(6)}"
                safety_repo.insert_bridge(
                    conn,
                    {
                        "id": bridge_id,
                        "borrower_slug": decision.borrower,
                        "lender_slug": slug,
                        "amount": amount,
                        "reason": decision.reason,
                        "status": "pending_approval",
                        "mode": "auto" if auto else "approval",
                        "shortfall_date": decision.shortfall_date,
                        "due_date": decision.due_date,
                        "approval_channel": None,
                        "borrower_floor": decision.floor,
                        "agreement_version": versions.get(slug),
                        "decision_id": decision_id,
                    },
                )
                ids.append(bridge_id)
        except psycopg.errors.UniqueViolation:  # the database's own one-open-bridge-per-pair rule
            conn.rollback()
            return None
        if not auto:
            b = safety_repo.bridge(conn, ids[0])
            channel = _request_approval(conn, b)
            where = "on your phone" if channel == "auth0_push" else "in Runway"
            _both(
                conn,
                b,
                "approval_needed",
                f"Asked {b['lender_name']} to approve ${decision.amount:,.0f} of support.",
                # the supporter learns who and how much — never when or why someone runs short
                f"🔔 {b['borrower_name']} could use ${decision.amount:,.0f} of support (over your auto limit). "
                f"Approve {where} — expected back {_md(decision.due_date)}.",
            )
        conn.commit()
    if not auto:
        with pool.connection() as conn:
            return safety_repo.bridge(conn, ids[0])
    funded = [b for b in (_fund(i) for i in ids) if b is not None]
    if decision.held:  # audit only: telling a held-back supporter would reveal WHEN their person was short
        log.info("decision for %s protected %s", decision.borrower, [(s, why) for s, _, why in decision.held])
    if len(funded) < len(ids):  # some shares landed, some didn't: say so, never "covered"
        got = sum((Decimal(b["amount"]) for b in funded), Decimal(0))
        with pool.connection() as conn:
            safety_repo.add_event(
                conn,
                decision.borrower,
                "partially_covered",
                f"Your safety net covered {_money(got)} of {_money(decision.amount)} — the rest didn't go through.",
            )
            conn.commit()
    return funded[0] if funded else None


def withdraw_requests(borrower_slug: str) -> int:
    """Family cover was just turned off: withdraw every request still waiting for a relative's answer,
    so nobody is left being asked. Returns how many were withdrawn. (_fund re-checks the switch too,
    for an answer that arrives at the same moment.)"""
    withdrawn = 0
    with pool.connection() as conn:
        for b in safety_repo.bridges_for(conn, borrower_slug):
            if b["borrower_slug"] != borrower_slug or b["status"] != "pending_approval":
                continue
            if safety_repo.transition(conn, b["id"], ("pending_approval",), "declined"):
                withdrawn += 1
                _both(
                    conn,
                    b,
                    "bridge_declined",
                    f"You turned family cover off, so {b['lender_name']} isn't being asked anymore.",
                    f"{b['borrower_name']} doesn't need this one anymore. Nothing was moved.",
                )
        conn.commit()
    return withdrawn


def approve(bridge_id: str) -> dict | None:
    """The lender approved (in-app, or via the Auth0 push)."""
    return _fund(bridge_id)


def decline(bridge_id: str) -> dict | None:
    with pool.connection() as conn:
        current = safety_repo.bridge(conn, bridge_id)
        if current is None:
            return None
        safety_repo.lock_people(conn, current["lender_slug"], current["borrower_slug"])
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


class RepayRefused(Exception):
    """An early repayment that isn't allowed; the message is safe to show the borrower."""


def _checking_balance(conn, persona: dict) -> Decimal:
    return next(
        Decimal(a["balance"])
        for a in repo.accounts_with_balances(conn, persona["customer_id"])
        if a["id"] == persona["checking_id"]
    )


def _repay_floor(conn, b: dict) -> Decimal:
    """What repaying a bridge must leave the borrower with: the LOWER of their floor when they were
    helped and their floor now. Raising it after being helped can't stall paying the family back;
    lowering it lets the money go back sooner."""
    now = Decimal(str(prefs.floor(b["borrower_slug"], conn, strict=True)))
    then = b.get("borrower_floor")
    return now if then is None else min(now, Decimal(str(then)))


def _pay_back(b: dict, *, early: bool) -> dict | None:
    """Move a bridge's money borrower → lender. Claims the bridge first (active / repay_failed →
    repaying) and journals the attempt in the same transaction, so on-time and early repayments can
    never both happen. A retry is only ever made after an attempt that certainly moved nothing."""
    with pool.connection() as conn:
        claimed = safety_repo.transition(conn, b["id"], ("active", "repay_failed"), "repaying")
        if claimed is None:
            conn.rollback()
            return None
        attempts = journal_repo.for_ref(conn, b["id"], "repay")
        if any(a["state"] != "not_made" for a in attempts):
            conn.rollback()  # an earlier attempt may have landed: reconcile it, never pay again
            log.error("repayment of %s has an unsettled earlier attempt; not sending", b["id"])
            return None
        borrower, lender = repo.persona(conn, b["borrower_slug"]), repo.persona(conn, b["lender_slug"])
        key = f"repay:{b['id']}:{len(attempts) + 1}"
        amount = float(b["amount"])
        journal_repo.claim(conn, key, "repay", b["id"], borrower["checking_id"], lender["checking_id"], amount)
        conn.commit()
    try:
        t_id, d_id = _move(
            borrower,
            lender,
            amount,
            f"Safety net repayment to {b['lender_name']}",
            f"Repaid by {b['borrower_name']} (safety net)",
            key=key,
        )
    except TransferNotMade as e:
        with pool.connection() as conn:
            journal_repo.finish(conn, key, "not_made", error=str(e))
            safety_repo.transition(conn, b["id"], ("repaying",), "repay_failed")  # safe to try again later
            conn.commit()
        log.warning("repayment of %s not made: %s", b["id"], e)
        return None
    except Exception as e:  # unclear outcome: reconcile against Nessie, never retry
        with pool.connection() as conn:
            journal_repo.finish(conn, key, "unknown", error=str(e))
            safety_repo.transition(conn, b["id"], ("repaying",), "reconcile")
            _both(conn, b, "bridge_checking", CHECKING_WITH_BANK, CHECKING_WITH_BANK)
            conn.commit()
        log.exception("repayment of %s outcome unknown — reconciling", b["id"])
        return None
    with pool.connection() as conn:
        journal_repo.finish(conn, key, "succeeded", transfer_id=t_id, deposit_id=d_id)
        row = _repaid(conn, b["id"], ("repaying",), t_id, d_id, early=early)
        conn.commit()
    return row


def _repaid(conn, bridge_id: str, frm: tuple[str, ...], t_id: str, d_id: str, *, early: bool) -> dict | None:
    row = safety_repo.transition(
        conn, bridge_id, frm, "repaid", repaid_at=datetime.now(LOCAL_TZ), back_transfer_id=t_id, back_deposit_id=d_id
    )
    if row is None:
        return None
    amount = float(row["amount"])
    if early:
        _both(
            conn,
            row,
            "repaid",
            f"✅ You paid {row['lender_name']} back ${amount:,.0f} early.",
            f"💸 {row['borrower_name']} paid you back ${amount:,.0f} early.",
        )
    else:
        _both(
            conn,
            row,
            "repaid",
            f"✅ Repaid {row['lender_name']} ${amount:,.0f} from your paycheck.",
            f"💸 You got your ${amount:,.0f} back from {row['borrower_name']}.",
        )
    return row


def reconcile_pending() -> int:
    """Settle money moves whose outcome was unclear, by looking for their tag in Nessie. Only "it
    happened" is concluded automatically; anything else stays `reconcile` (see app/reconcile.py).
    Returns how many were settled."""
    settled = 0
    with pool.connection() as conn:
        rows = [r for r in journal_repo.unresolved(conn, STUCK_AFTER) if r["kind"] in ("fund", "repay")]
    for r in rows:
        with _in_flight_lock:
            if r["key"] in _IN_FLIGHT:
                continue
        try:
            verdict, t_id, d_id = reconcile.resolve(NessieClient.from_settings(), r)
        except Exception:
            log.exception("could not reconcile %s", r["key"])
            continue
        with pool.connection() as conn:
            if verdict == "succeeded" and journal_repo.finish(
                conn, r["key"], "succeeded", transfer_id=t_id, deposit_id=d_id
            ):
                if r["kind"] == "fund":
                    _funded(conn, r["ref"], ("funding", "reconcile"), t_id, d_id)
                else:
                    _repaid(conn, r["ref"], ("repaying", "reconcile"), t_id, d_id, early=False)
                settled += 1
            elif verdict == "reconcile":
                if r["state"] == "started":  # the process stopped mid-call: no answer was ever recorded
                    journal_repo.finish(conn, r["key"], "unknown", error="no answer recorded; checking Nessie")
                b = safety_repo.transition(conn, r["ref"], ("funding", "repaying"), "reconcile")
                if b:
                    _both(conn, b, "bridge_checking", CHECKING_WITH_BANK, CHECKING_WITH_BANK)
            conn.commit()
    return settled


def _safe_to_repay(conn, b: dict, borrower: dict, keep: Decimal, today: date) -> bool:
    """All must hold before paying a bridge back: (1) a real paycheck has landed since the bridge was
    funded — not just "the date passed"; (2) the balance stays at or above the cushion after repaying;
    (3) the forecast for the next week doesn't dip under the cushion because of the repayment."""
    amount = Decimal(b["amount"])
    if _checking_balance(conn, borrower) - amount < keep:
        return False
    p = project(conn, b["borrower_slug"], today)
    since = b["funded_at"].astimezone(LOCAL_TZ).date() if b.get("funded_at") else b["due_date"]
    at_least = p.paycheck / 2 if p.paycheck else amount
    if not repo.paycheck_landed(conn, borrower["checking_id"], since, at_least):
        return False
    low = p.low(today, today + timedelta(days=REPAY_CHECK_DAYS))
    already_scheduled = b["due_date"] >= today  # project() books this repayment on its due date
    return low is not None and low[1] - (Decimal(0) if already_scheduled else amount) >= keep


def repay_due(today: date | None = None) -> list[dict]:
    """On (or after) the due date, pay each lender back — but never push the borrower under the floor."""
    today, done = today or _today(), []
    with pool.connection() as conn:
        due = [
            b
            for b in safety_repo.outstanding_bridges(conn)
            if b["due_date"] <= today and b["status"] in ("active", "repay_failed")  # never repaying/reconcile
        ]
    for b in due:
        with pool.connection() as conn:
            borrower = repo.persona(conn, b["borrower_slug"])
            keep = _repay_floor(conn, b)
            if not _safe_to_repay(conn, b, borrower, keep, today):  # paycheck not in yet, or it'd cause a dip
                if (today - b["due_date"]).days >= REPAY_GRACE_DAYS and b["status"] == "active":
                    safety_repo.transition(conn, b["id"], ("active",), "repay_failed")
                    _both(
                        conn,
                        b,
                        "repay_late",
                        f"Your ${b['amount']:,.0f} repayment to {b['lender_name']} is waiting — it goes back "
                        "after your next verified payday, when it won't cause a shortfall.",
                        f"{b['borrower_name']}'s ${b['amount']:,.0f} repayment is expected after their next "
                        "verified payday. No new support to them until it's back.",
                    )
                    conn.commit()
                continue
        row = _pay_back(b, early=False)
        if row is not None:
            done.append(row)
    return done


def repay_now(bridge_id: str) -> dict:
    """The borrower pays a bridge back before payday. Refused (RepayRefused) if the bridge isn't out,
    or if paying now would take the borrower under the floor — the dip the bridge was there to stop."""
    with pool.connection() as conn:
        b = safety_repo.bridge(conn, bridge_id)
        if b is None or b["status"] not in ("active", "repay_failed"):
            raise RepayRefused("That bridge isn't waiting to be paid back.")
        borrower = repo.persona(conn, b["borrower_slug"])
        keep = _repay_floor(conn, b)
        if _checking_balance(conn, borrower) - Decimal(b["amount"]) < keep:
            raise RepayRefused(
                f"Paying back now would take you under {_money(keep)}, the amount you keep. "
                f"It goes back automatically on payday, {_wmd(b['due_date'])}."
            )
    row = _pay_back(b, early=True)
    if row is None:
        raise RepayRefused("That didn't go through — we're checking with the bank. It's retried on payday.")
    return row


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
    reconcile_pending()
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

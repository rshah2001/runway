"""Where the forecast's inputs come from — owner: Patil-Hemangi.

Live mode reads Tiger Data through `app.db.repo` (owned by the data team; this module only reads).
Without live credentials (CI, tests, offline laptops), or if the database read fails mid-demo, the
same persona is rebuilt from `seed.plan.build_plan` — the exact generator that seeded Nessie — so
offline and live runs look the same.

Everything is normalised to `PersonaData`, so the engine never knows which source it came from.
"""

import logging
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from app.config import get_settings
from seed.personas import MERCHANTS, PERSONAS, PersonaSpec
from seed.plan import HISTORY_DAYS, build_plan, demo_opening_balance

log = logging.getLogger(__name__)
LOCAL_TZ = ZoneInfo("America/New_York")  # the demo's bank day; the server itself runs on UTC

Account = Literal["Checking", "Savings", "Credit Card"]
TxnKind = Literal["purchase", "deposit", "transfer", "withdrawal", "bill"]


class UnknownPersona(LookupError):
    pass


@dataclass(frozen=True)
class Txn:
    date: date
    kind: TxnKind
    amount: float  # signed from the account's point of view: negative = money out (same as the database)
    label: str  # merchant name, or the description for deposits, transfers and bills
    category: str
    account: Account


@dataclass(frozen=True)
class UpcomingBill:
    day: int  # day of month it is paid from checking
    amount: float  # positive
    label: str


@dataclass(frozen=True)
class PersonaData:
    slug: str
    checking: float
    savings: float
    bills: list[UpcomingBill]
    history: list[Txn] = field(default_factory=list)  # oldest first


def local_today() -> date:
    return datetime.now(LOCAL_TZ).date()


def recent(data: PersonaData, today: date, days: int) -> PersonaData:
    """The same persona with only the last `days` of history, as if Runway had just met them."""
    cutoff = today - timedelta(days=max(0, days))
    return replace(data, history=[t for t in data.history if t.date >= cutoff])


class LiveDataUnavailable(RuntimeError):
    """`strict=True` and real data couldn't be read — the caller must not act on a guess."""


def load(persona: str, today: date | None = None, *, strict: bool = False) -> PersonaData:
    """One persona's balances, scheduled bills and recent history, live if possible.

    `strict=True` is for anything that moves money (the safety net): it never falls back to seeded
    demo data, so a failed read aborts the decision instead of acting on made-up balances.
    """
    today = today or local_today()
    if get_settings().live:
        try:
            return _load_live(persona, today)
        except UnknownPersona:
            raise
        except Exception as e:  # a dead database must not take the chatbot down mid-demo…
            if strict:  # …but it must stop anything that moves money
                raise LiveDataUnavailable(f"live data for {persona} unavailable") from e
            log.exception("forecast inputs: live read failed for %s, using seeded demo data", persona)
    elif strict:
        raise LiveDataUnavailable("not in live mode")
    return _load_demo(persona, today)


# ---------- live: Tiger Data ----------


def _load_live(persona: str, today: date) -> PersonaData:
    from app.db import pool, repo  # imported lazily: offline runs never need a database driver

    since = datetime.combine(today - timedelta(days=HISTORY_DAYS), datetime.min.time(), LOCAL_TZ)
    until = datetime.combine(today, datetime.min.time(), LOCAL_TZ)
    with pool.connection() as conn:
        p = repo.persona(conn, persona)
        if p is None:
            raise UnknownPersona(persona)
        balances = {a["type"]: float(a["balance"]) for a in repo.accounts_with_balances(conn, p["customer_id"])}
        bills = [
            UpcomingBill(day=int(b["recurring_day"]), amount=float(b["amount"]), label=b["nickname"])
            for b in repo.bills(conn, p["customer_id"])
            if b["account_type"] == "Checking" and b["recurring_day"]
        ]
        rows = repo.transactions(conn, p["customer_id"], since, until)
    history = [
        Txn(
            date=r["ts"].astimezone(LOCAL_TZ).date(),
            kind=r["kind"],
            amount=float(r["amount"]),
            label=r["merchant"] or r["description"] or "Unknown",
            category=r["category"] or "Other",
            account=r["account_type"],
        )
        for r in rows
        if r["status"] == "completed"
    ]
    return PersonaData(persona, balances.get("Checking", 0.0), balances.get("Savings", 0.0), bills, history)


# ---------- offline: the seed generator ----------

_ACCOUNT: dict[str, Account] = {"checking": "Checking", "savings": "Savings", "credit": "Credit Card"}


def _spec(persona: str) -> PersonaSpec:
    spec = next((s for s in PERSONAS if s.slug == persona), None)
    if spec is None:
        raise UnknownPersona(persona)
    return spec


def _load_demo(persona: str, today: date) -> PersonaData:
    spec = _spec(persona)
    plan = build_plan(spec, today)
    # the seed tunes some personas' opening balance to tell the same demo story on any day; match it
    checking = demo_opening_balance(spec, plan, today) if spec.demo_low_before_payday else spec.checking
    return demo_data(spec, plan, checking)


def demo_data(spec: PersonaSpec, plan: list, checking: float) -> PersonaData:
    """PersonaData built straight from a seed plan (also used by the seed to tune demo balances)."""
    history: list[Txn] = []
    for op in plan:
        account = _ACCOUNT[op.account]
        if op.kind == "purchase":
            category = MERCHANTS[op.merchant][0] if op.merchant in MERCHANTS else "Other"
            history.append(Txn(op.on, "purchase", -op.amount, op.merchant or op.description, category, account))
        elif op.kind == "deposit":
            history.append(Txn(op.on, "deposit", op.amount, op.description, "Income", account))
        elif op.kind == "bill" and op.bill_status == "completed":
            history.append(Txn(op.on, "bill", -op.amount, op.description, "Bills", account))
        elif op.kind == "p2p":  # seeded as a deposit in, or a transfer out, of checking
            incoming = op.direction == "in"
            kind: TxnKind = "deposit" if incoming else "transfer"
            history.append(Txn(op.on, kind, op.amount if incoming else -op.amount, op.description, "P2P", account))
    bills = [UpcomingBill(b.day, b.amount, b.nickname) for b in spec.bills]
    return PersonaData(spec.slug, checking, spec.savings, bills, sorted(history, key=lambda t: t.date))

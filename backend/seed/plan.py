"""Turn a persona spec into the exact list of Nessie writes. Pure and deterministic: same persona +
same day → same plan, so history is reproducible and the forecast backtest has a stable dataset."""

import calendar
import random
from dataclasses import dataclass
from datetime import date, timedelta

from seed.personas import PersonaSpec

HISTORY_DAYS = 120  # ~4 months: months 1–3 to fit a model, month 4 to backtest it


@dataclass(frozen=True)
class Op:
    kind: str  # "purchase" | "deposit" | "bill" | "p2p"
    account: str  # "checking" | "savings" | "credit"
    amount: float
    on: date
    description: str
    merchant: str | None = None
    bill_status: str | None = None  # "completed" history or "recurring" upcoming
    payee: str | None = None
    day: int | None = None
    contact: str | None = None  # p2p: Contact.key
    direction: str | None = None  # p2p: "in" (contact → persona) or "out" (persona → contact)


def _monthly(day: int, start: date, end: date) -> list[date]:
    """Every occurrence of `day` (clamped to month length) in [start, end)."""
    out, y, m = [], start.year, start.month
    while date(y, m, 1) < end:
        d = date(y, m, min(day, calendar.monthrange(y, m)[1]))
        if start <= d < end:
            out.append(d)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def next_monthly(day: int, today: date) -> date:
    return _monthly(day, today, today + timedelta(days=62))[0]


def paydays(spec: PersonaSpec, start: date, today: date) -> list[date]:
    p = spec.paycheck
    if p.every_days is None:
        return _monthly(p.day, start, today)
    # the next payday is always the coming Friday (never today), so the demo opens before payday
    nxt = today + timedelta(days=(4 - today.weekday()) % 7 or 7)
    days, d = [], nxt - timedelta(days=p.every_days)
    while d >= start:
        days.append(d)
        d -= timedelta(days=p.every_days)
    return sorted(days)


def build_plan(spec: PersonaSpec, today: date) -> list[Op]:
    """History strictly before `today`, plus one upcoming recurring bill per scheduled bill."""
    start = today - timedelta(days=HISTORY_DAYS)
    rng = random.Random(f"{spec.slug}-{today.isoformat()}")
    ops: list[Op] = []

    for d in paydays(spec, start, today):
        ops.append(Op("deposit", "checking", spec.paycheck.amount, d, spec.paycheck.label))

    for b in spec.bills:
        for d in _monthly(b.day, start, today):
            ops.append(
                Op("bill", "checking", b.amount, d, b.nickname, bill_status="completed", payee=b.payee, day=b.day)
            )
        ops.append(
            Op(
                "bill",
                "checking",
                b.amount,
                next_monthly(b.day, today),
                b.nickname,
                bill_status="recurring",
                payee=b.payee,
                day=b.day,
            )
        )

    for s in spec.subscriptions:
        for d in _monthly(s.day, start, today):
            ops.append(Op("purchase", "credit", s.amount, d, f"{s.merchant} subscription", merchant=s.merchant))

    d = start
    while d < today:
        for h in spec.habits:
            if rng.random() < h.per_week / 7:
                amount = round(h.low + rng.random() * (h.high - h.low), 2)
                ops.append(Op("purchase", h.account, amount, d, h.merchant, merchant=h.merchant))
        d += timedelta(days=1)

    # peer-to-peer: its own RNG so adding a split never reshuffles the purchase history
    p2p_rng = random.Random(f"{spec.slug}-p2p-{today.isoformat()}")
    for pat in spec.p2p:
        if pat.day is not None:
            days = _monthly(pat.day, start, today)
            amounts = [pat.amount] * len(days)
        else:
            days, amounts, d = [], [], start
            while d < today:
                if p2p_rng.random() < pat.per_month / 30:
                    days.append(d)
                    amounts.append(round(pat.amount * (0.6 + 0.8 * p2p_rng.random()), 2))
                d += timedelta(days=1)
        for d, amount in zip(days, amounts, strict=True):
            ops.append(Op("p2p", "checking", amount, d, pat.memo, contact=pat.contact, direction=pat.direction))

    return sorted(ops, key=lambda o: (o.on, o.kind, o.description))

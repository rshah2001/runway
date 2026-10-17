"""Scheduled cash-flow projection for one persona's checking account — what the safety net uses to
spot a dip before it happens and to check that helping is safe for the helper.

Deliberately simple and explainable: today's live balance, minus upcoming bills, plus detected
paydays, minus typical daily debit spending, plus/minus bridge repayments already scheduled.
When the forecast engine (app/forecast) becomes persona-aware it can replace `project()` — the
safety net only depends on the `Projection` it returns.
"""

import calendar
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

import psycopg

from app.db import repo, safety_repo

LOCAL_TZ = ZoneInfo("America/New_York")
PAYCHECK_MIN = Decimal("200")  # deposits smaller than this aren't treated as income
CENT = Decimal("0.01")


@dataclass(frozen=True)
class Projection:
    slug: str
    first_name: str
    age: int
    start_balance: Decimal
    days: list[tuple[date, Decimal]]  # end-of-day checking balance, starting today
    next_payday: date | None
    paycheck: Decimal | None
    events: list[tuple[date, Decimal, str]] = field(default_factory=list)  # what moved the balance

    def low(self, start: date, end: date) -> tuple[date, Decimal] | None:
        """Lowest end-of-day balance in [start, end)."""
        window = [(d, b) for d, b in self.days if start <= d < end]
        return min(window, key=lambda x: x[1]) if window else None

    def balance_on(self, d: date) -> Decimal | None:
        return next((b for day, b in self.days if day == d), None)


def _monthly_on(day: int, start: date, end: date) -> list[date]:
    out, y, m = [], start.year, start.month
    while date(y, m, 1) <= end:
        d = date(y, m, min(day, calendar.monthrange(y, m)[1]))
        if start <= d <= end:
            out.append(d)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def detect_paydays(
    deposits: list[tuple[date, Decimal]], today: date, horizon: date
) -> tuple[list[date], Decimal | None]:
    """Find the recurring paycheck in past deposits: the most common amount seen at least twice,
    then project its cadence (≈14 days → biweekly, ≈30 → monthly on the same day) forward."""
    by_amount: dict[Decimal, list[date]] = {}
    for d, amount in deposits:
        if amount >= PAYCHECK_MIN:
            by_amount.setdefault(amount, []).append(d)
    candidates = [(amt, sorted(ds)) for amt, ds in by_amount.items() if len(ds) >= 2]
    if not candidates:
        return [], None
    amount, dates = max(candidates, key=lambda c: (len(c[1]), c[0]))
    gap = statistics.median((b - a).days for a, b in zip(dates, dates[1:], strict=False))
    future: list[date] = []
    if 25 <= gap <= 35:
        future = [d for d in _monthly_on(dates[-1].day, today, horizon) if d > today]
    else:
        nxt = dates[-1] + timedelta(days=int(gap))
        while nxt <= horizon:
            if nxt > today:
                future.append(nxt)
            nxt += timedelta(days=int(gap))
    return future, amount


def build_projection(
    *,
    slug: str,
    first_name: str,
    age: int,
    today: date,
    balance: Decimal,
    bills: list[tuple[int, Decimal, str]],  # (day of month, amount, name) paid from checking
    deposits: list[tuple[date, Decimal]],  # past deposits, for payday detection
    daily_spend: Decimal,
    scheduled: list[tuple[date, Decimal, str]] = (),  # e.g. bridge repayments: (date, signed amount, label)
    days: int = 35,
) -> Projection:
    """Pure: turn the inputs into a day-by-day balance. Income lands before bills on the same day."""
    horizon = today + timedelta(days=days - 1)
    paydays, paycheck = detect_paydays(deposits, today, horizon)
    moves: list[tuple[date, Decimal, str]] = [(d, paycheck, "Paycheck") for d in paydays]
    for day, amount, name in bills:
        moves += [(d, -amount, name) for d in _monthly_on(day, today, horizon)]  # a bill due today is still unpaid
    moves += [m for m in scheduled if today <= m[0] <= horizon]
    moves.sort(key=lambda m: (m[0], m[1] < 0))  # same day: money in first

    out, bal, i = [], balance, 0
    for n in range(days):
        d = today + timedelta(days=n)
        if n:  # today's spending is already in the live balance
            bal -= daily_spend
        while i < len(moves) and moves[i][0] == d:
            bal += moves[i][1]
            i += 1
        out.append((d, bal.quantize(CENT, ROUND_HALF_UP)))
    return Projection(slug, first_name, age, balance, out, paydays[0] if paydays else None, paycheck, moves)


def project(conn: psycopg.Connection, slug: str, today: date | None = None, days: int = 35) -> Projection:
    """Load one persona's inputs from Tiger Data and project their checking balance."""
    today = today or datetime.now(LOCAL_TZ).date()
    p = repo.persona(conn, slug)
    accounts = {a["id"]: a for a in repo.accounts_with_balances(conn, p["customer_id"])}
    balance = Decimal(accounts[p["checking_id"]]["balance"])
    bills = [
        (b["recurring_day"], Decimal(b["amount"]), b["nickname"])
        for b in repo.bills(conn, p["customer_id"])
        if b["account_id"] == p["checking_id"] and b["recurring_day"]
    ]
    since = datetime.combine(today - timedelta(days=90), datetime.min.time(), LOCAL_TZ)
    history = repo.transactions(conn, p["customer_id"], since)
    deposits = [
        (t["ts"].astimezone(LOCAL_TZ).date(), Decimal(t["amount"]))
        for t in history
        if t["kind"] == "deposit"
        and t["account_id"] == p["checking_id"]
        and not (t["description"] or "").startswith("From ")
    ]
    month_ago = today - timedelta(days=30)
    debit = [
        -Decimal(t["amount"])
        for t in history
        if t["kind"] == "purchase"
        and t["account_id"] == p["checking_id"]
        and t["ts"].astimezone(LOCAL_TZ).date() >= month_ago
    ]
    daily_spend = (sum(debit, Decimal(0)) / 30).quantize(CENT) if debit else Decimal(0)

    scheduled = []
    for b in safety_repo.outstanding_bridges(conn):
        if b["borrower_slug"] == slug:
            scheduled.append((b["due_date"], -Decimal(b["amount"]), f"Repay {b['lender_name']}"))
        elif b["lender_slug"] == slug:
            scheduled.append((b["due_date"], Decimal(b["amount"]), f"{b['borrower_name']} pays you back"))
    return build_projection(
        slug=slug,
        first_name=p["first_name"],
        age=p["age"] or 0,
        today=today,
        balance=balance,
        bills=bills,
        deposits=deposits,
        daily_spend=daily_spend,
        scheduled=scheduled,
        days=days,
    )

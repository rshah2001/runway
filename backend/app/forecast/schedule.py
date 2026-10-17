"""The cash flows the forecast engine projects for one persona — owner: Patil-Hemangi.

A `Schedule` is plain data, built from a persona's real inputs (`sources.PersonaData`):
  * bills from the bills table — known amounts on known days;
  * regular money in and out of checking (paychecks, fixed transfers), detected from history;
  * everyday spending, learned from the last 90 days of checking outflows that are neither.
Keeping it separate from the engine makes the engine a pure function of (schedule, start, horizon),
which is what lets the backtest fit a schedule on months 1–3 and score it on month 4.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Literal

from app.forecast import readiness
from app.forecast.recurring import detect_recurring
from app.forecast.sources import PersonaData, Txn
from app.forecast.spend_model import Outflows, SpendProfile, daily_totals, fit_flat
from app.schemas import Readiness

EventKind = Literal["paycheck", "bill", "subscription", "card_payment", "spending", "transfer", "other"]

SAFE_FLOOR = 300.0
SPEND_WINDOW_DAYS = 90  # the backtest's training window: long enough to smooth out one odd week


@dataclass(frozen=True)
class MonthlyCharge:
    """A fixed charge on the same day each month; days past month-end clamp to the last day."""

    day: int
    amount: float  # positive = money out
    label: str
    kind: EventKind = "bill"


@dataclass(frozen=True)
class RegularFlow:
    """Money that reliably moves in or out of checking on a cadence, found in history."""

    label: str
    amount: float  # signed: positive = money in
    interval_days: int
    next_date: date
    kind: EventKind


@dataclass(frozen=True)
class Schedule:
    start_balance: float  # checking only: savings is the cushion, not spending money
    safe_floor: float = SAFE_FLOOR
    monthly: list[MonthlyCharge] = field(default_factory=list)
    regular: list[RegularFlow] = field(default_factory=list)
    spend: SpendProfile = SpendProfile((0.0,) * 7)
    readiness: Readiness | None = None  # how sure a forecast from this schedule is
    daily_spend: tuple[float, ...] = ()  # each day's everyday spending in the learning window: the range


def _checking_flow(t: Txn) -> bool:
    """Money moving in or out of checking other than purchases and bills."""
    return t.account == "Checking" and t.kind in ("deposit", "transfer", "withdrawal")


def regular_flows(history: list[Txn], today: date) -> list[RegularFlow]:
    """Paychecks and fixed transfers that repeat on a steady cadence for a steady amount."""
    incoming = detect_recurring(history, today, lambda t: _checking_flow(t) and t.amount > 0)
    outgoing = detect_recurring(history, today, lambda t: _checking_flow(t) and t.amount < 0)
    biggest_in = max((r.amount for r in incoming), default=0)
    flows = [
        # the largest steady income is the paycheck; smaller ones are splits and allowances
        RegularFlow(
            r.merchant, r.amount, r.interval_days, r.next_date, "paycheck" if r.amount == biggest_in else "transfer"
        )
        for r in incoming
    ]
    flows += [RegularFlow(r.merchant, -r.amount, r.interval_days, r.next_date, "transfer") for r in outgoing]
    return flows


def everyday_outflows(history: list[Txn], regular: list[RegularFlow]) -> Outflows:
    """Checking outflows that are neither bills nor a detected regular transfer: debit purchases,
    occasional transfers. Card purchases are left out — they reach checking as the card-payment bill."""
    regular_labels = {f.label.strip().lower() for f in regular}
    return [
        (t.date, -t.amount)
        for t in history
        if t.account == "Checking"
        and t.amount < 0
        and t.kind in ("purchase", "transfer", "withdrawal")
        and t.label.strip().lower() not in regular_labels
    ]


def spend_window(data: PersonaData, today: date) -> tuple[date, date]:
    """The days the spending rate is learned from: the last SPEND_WINDOW_DAYS, or since the first day
    with data if that is more recent. Dividing a new user's 12 days of spending by 90 would make them
    look like they barely spend."""
    first = readiness.history_start(data) or today
    return max(today - timedelta(days=SPEND_WINDOW_DAYS), first), today


def build(data: PersonaData, today: date, fit=fit_flat) -> Schedule:
    """A persona's schedule as of `today`, learned from the history before it."""
    regular = regular_flows(data.history, today)
    start, end = spend_window(data, today)
    outflows = everyday_outflows(data.history, regular)
    spend = fit(outflows, start, end)
    monthly = [
        MonthlyCharge(b.day, b.amount, b.label, "card_payment" if "credit card" in b.label.lower() else "bill")
        for b in data.bills
    ]
    paycheck = next(((f.label, f.amount, f.interval_days) for f in regular if f.kind == "paycheck"), None)
    ready = readiness.assess(data, today, spend_days=(end - start).days, paycheck=paycheck)
    return Schedule(
        start_balance=data.checking,
        monthly=monthly,
        regular=regular,
        spend=spend,
        readiness=ready,
        daily_spend=daily_totals(outflows, start, end),
    )

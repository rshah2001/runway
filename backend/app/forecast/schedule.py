"""The recurring cash flows the forecast engine projects — owner: Patil-Hemangi.

A `Schedule` is plain data: starting balance, paychecks, bills, card statements and spending
estimates. Keeping it separate from the engine means the engine is a pure function of
(schedule, start, horizon), which is what makes it testable and backtestable. Today the only
schedule is the fictional demo persona; later one is built from Nessie bills, deposits and purchases.
"""

from dataclasses import dataclass, field
from typing import Literal

EventKind = Literal["paycheck", "bill", "subscription", "card_payment", "spending", "transfer", "other"]


@dataclass(frozen=True)
class Paycheck:
    amount: float
    every_days: int
    label: str
    weekday: int = 4  # 0 = Monday; paychecks land on Fridays


@dataclass(frozen=True)
class MonthlyCharge:
    """A fixed charge on the same day each month; days past month-end clamp to the last day."""

    day: int
    amount: float  # positive = money out
    label: str
    kind: EventKind = "bill"


@dataclass(frozen=True)
class Installment:
    """Fixed monthly payments starting next month until `months_left` run out."""

    day: int
    monthly: float
    months_left: int
    label: str


@dataclass(frozen=True)
class CardStatement:
    """A credit card paid in full on `pay_day`.

    Only the current statement balance is known, so only the next payoff is projected. Later
    statements depend on new charges, which the spending estimates below already count once.
    """

    label: str
    balance: float
    pay_day: int


@dataclass(frozen=True)
class Schedule:
    start_balance: float  # checking only: savings is the cushion, not spending money
    safe_floor: float
    paycheck: Paycheck
    monthly: list[MonthlyCharge] = field(default_factory=list)
    installments: list[Installment] = field(default_factory=list)
    cards: list[CardStatement] = field(default_factory=list)
    weekly_spend: float = 0.0  # groceries estimate, charged every 7 days from the start
    monthly_spend: float = 0.0  # discretionary estimate (eating out, one-offs), charged on the 10th


# Fictional demo persona — the same numbers as PERSONA in prototype/index.html. Not a real person.
MAYA = Schedule(
    start_balance=680.00,
    safe_floor=300.00,
    paycheck=Paycheck(amount=780.00, every_days=14, label="Campus job paycheck"),
    monthly=[
        MonthlyCharge(1, 650.00, "Rent"),
        MonthlyCharge(5, 62.00, "Electric + internet"),
        MonthlyCharge(12, 108.00, "Car insurance"),
        MonthlyCharge(20, 35.00, "Phone bill"),
        MonthlyCharge(8, 11.99, "Music streaming", "subscription"),
        MonthlyCharge(14, 15.49, "Video streaming", "subscription"),
        MonthlyCharge(17, 9.99, "Cloud storage", "subscription"),
    ],
    installments=[Installment(28, 83.25, 9, "Laptop — 0% installments")],
    cards=[CardStatement("Rewards credit card", 286.40, pay_day=22)],
    weekly_spend=55.00,
    monthly_spend=120.00,
)

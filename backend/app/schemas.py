"""API contract shared by the app and the backend.

Changing a model here changes the contract: do it in its own PR and update
`app/src/lib/types.ts` in the same PR so web, iOS and Android stay in sync.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class Account(BaseModel):
    id: str
    nickname: str
    type: Literal["Checking", "Savings", "Credit Card"]
    balance: float


class Me(BaseModel):
    customer_id: str
    first_name: str
    accounts: list[Account]


class ForecastPoint(BaseModel):
    date: date
    balance: float  # expected end-of-day balance
    balance_low: float | None = None  # p5: the cautious end, if everyday spending runs high
    balance_high: float | None = None  # p90


class ForecastEvent(BaseModel):
    date: date
    amount: float  # negative = money out
    label: str
    kind: Literal["paycheck", "bill", "subscription", "card_payment", "spending", "transfer", "other"]


class LeftOut(BaseModel):
    """A one-off purchase kept out of the everyday spending rate (it still counts in the range)."""

    date: date
    amount: float  # positive
    label: str


class Readiness(BaseModel):
    """How sure the forecast is (backend/app/forecast/readiness.py). Every figure is the engine's."""

    status: Literal["calibrating", "learning", "confident"]
    days_of_history: int
    paychecks_seen: int
    paycheck_found: bool  # the forecast has a learned payday in it
    paycheck_provisional: bool = False  # it's counting on a payday seen only twice so far
    spend_days: int  # days the everyday spending rate was learned from
    progress: float  # 0–1 toward "confident"
    reasons: list[str]  # plain English, safe to show as-is
    rolling_error: float | None = None  # $: how far off its week-ahead forecasts were, on average, lately
    rolling_error_days: int = 0  # how many recent days that average covers
    left_out: list[LeftOut] = Field(default_factory=list)  # one-offs kept out of the spending rate


class Forecast(BaseModel):
    points: list[ForecastPoint]
    low: ForecastPoint
    safe_floor: float
    events: list[ForecastEvent]
    readiness: Readiness | None = None  # None only for hand-built schedules (tests)
    cautious_low: ForecastPoint | None = None  # the day with the lowest p5 balance: what to plan around


class SimulateRequest(BaseModel):
    amount: float  # positive = a purchase you are considering
    date: date
    label: str = "Purchase"


class Recurring(BaseModel):
    merchant: str
    amount: float
    interval_days: int
    next_date: date


class PendingAction(BaseModel):
    id: str
    kind: Literal["transfer", "reschedule_bill"]
    description: str
    amount: float | None = None
    status: Literal["awaiting_approval", "approved", "declined", "executed", "failed"] = "awaiting_approval"


class ChatRequest(BaseModel):
    message: str
    persona: str = Field("maya", pattern=r"^[a-z]{1,32}$")  # TODO(auth): from the logged-in user


class ChatResponse(BaseModel):
    reply: str
    tool_calls: list[str] = []
    pending_action: PendingAction | None = None


class Persona(BaseModel):
    slug: str
    first_name: str
    age: int
    story: str


class CategorySpend(BaseModel):
    category: str
    spent: float
    purchases: int


class DailySpend(BaseModel):
    date: date
    spent: float


class SpendingTransaction(BaseModel):
    date: date
    merchant: str
    category: str
    amount: float  # positive = money spent
    account: str


class Spending(BaseModel):
    month: str  # "YYYY-MM"
    total: float
    categories: list[CategorySpend]  # biggest first
    daily: list[DailySpend]  # from the Tiger Data continuous aggregate in live mode
    transactions: list[SpendingTransaction]  # newest first


# ---------- peer-to-peer ----------
class Contact(BaseModel):
    id: str
    name: str
    relation: str
    owes_you: float  # total of their open requests


class P2PPayment(BaseModel):
    id: str
    date: date
    direction: Literal["in", "out"]  # in = the contact paid you
    contact_id: str
    contact: str
    amount: float
    memo: str


class P2PRequest(BaseModel):
    id: str
    contact_id: str
    contact: str
    amount: float  # the contact owes you this
    memo: str
    status: Literal["open", "settling", "paid", "declined", "failed"]
    created: date


class P2PSummary(BaseModel):
    contacts: list[Contact]
    payments: list[P2PPayment]  # newest first
    requests: list[P2PRequest]  # open first


PERSONA_SLUG = r"^[a-z]{1,32}$"


class P2PSend(BaseModel):
    persona: str = Field("maya", pattern=PERSONA_SLUG)
    contact_id: str = Field(pattern=r"^[a-z]{1,32}-[a-z]{1,32}$")
    amount: float = Field(gt=0, le=1000)  # demo cap per payment
    memo: str = Field(min_length=1, max_length=80)


# ---------- family safety net ----------
class SafetyLimit(BaseModel):
    lender: str
    lender_name: str
    borrower: str
    borrower_name: str
    limit: float  # moved without asking, if it comes back by the borrower's next payday
    outstanding: float  # lent and not back yet
    remaining: float
    enabled: bool


class Bridge(BaseModel):
    id: str
    borrower: str
    borrower_name: str
    lender: str
    lender_name: str
    amount: float
    reason: str
    status: Literal["pending_approval", "declined", "funding", "active", "repaying", "repaid", "repay_failed", "failed"]
    mode: Literal["auto", "approval"]  # auto = under the lender's limit, no ask
    approval_channel: Literal["auth0_push", "in_app"] | None
    shortfall_date: date  # the day the borrower would have dipped
    due_date: date  # repaid automatically on this payday
    created: date
    funded_on: date | None
    repaid_on: date | None  # shown to the lender: "you got it back"


class SafetyEvent(BaseModel):
    at: datetime
    kind: str
    message: str
    bridge_id: str | None


class ProjectedLow(BaseModel):
    date: date
    balance: float


class SafetyNetSummary(BaseModel):
    persona: str
    next_payday: date | None
    projected_low: ProjectedLow | None  # lowest balance before next payday
    limits_i_set: list[SafetyLimit]  # as a lender
    limits_for_me: list[SafetyLimit]  # family members covering me
    borrowed: list[Bridge]
    lent: list[Bridge]  # incl. due_date / repaid_on — when the money comes back
    approvals_waiting: list[Bridge]  # over-limit bridges waiting for MY approval
    events: list[SafetyEvent]  # newest first


class SafetyDecision(BaseModel):
    borrower: str
    action: Literal["none", "auto_bridge", "needs_approval", "no_safe_helper", "no_payday", "already_covered"]
    reason: str
    amount: float
    lender: str | None
    shortfall_date: date | None
    low_balance: float | None
    due_date: date | None
    executed: bool  # False = dry run (real writes off) or nothing to do
    bridge: Bridge | None


class SetLimit(BaseModel):
    lender: str = Field(pattern=PERSONA_SLUG)  # TODO(auth): must be the logged-in user
    borrower: str = Field(pattern=PERSONA_SLUG)
    limit: float = Field(ge=0, le=1000)
    enabled: bool = True

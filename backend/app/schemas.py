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
    safe_floor: float = 300.0  # what this person keeps in checking; every "am I okay?" uses it
    alerts_only: bool = False  # Today shows one calm line and speaks up only before a dip
    family_cover: bool = True  # False: family limits never move money to this person


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
    spend_days: int  # days the everyday spending rate was learned from
    progress: float  # 0–1 toward "confident"
    reasons: list[str]  # plain English, safe to show as-is
    rolling_error: float | None = None  # $: how far off its week-ahead forecasts were, on average, lately
    rolling_error_days: int = 0  # how many recent days that average covers
    # where that average comes from: "saved" = forecasts the app really showed, kept in Tiger Data and
    # checked once the day passed; "replay" = the engine re-run on past days (until enough are saved)
    rolling_error_source: Literal["saved", "replay"] | None = None
    band_coverage: float | None = None  # 0–1: share of checked days the real balance was inside the range
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
    kind: Literal["transfer", "reschedule_bill", "p2p_request"]  # p2p_request: ask a contact to pay you back
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
    # one per Send tap: a retried request with the same key returns the first payment, never a second
    client_key: str | None = Field(None, pattern=r"^[A-Za-z0-9-]{8,64}$")


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
    status: Literal[
        "pending_approval", "declined", "funding", "active", "repaying", "repaid", "repay_failed", "failed", "reconcile"
    ]
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
    action: Literal[
        "none", "auto_bridge", "needs_approval", "no_safe_helper", "no_payday", "already_covered", "family_off"
    ]
    reason: str
    amount: float
    lender: str | None
    shortfall_date: date | None
    low_balance: float | None
    due_date: date | None
    executed: bool  # False = dry run (real writes off) or nothing to do
    bridge: Bridge | None


class SetSafeFloor(BaseModel):
    persona: str = Field("maya", pattern=PERSONA_SLUG)  # ignored when signed in: you set your own
    amount: float = Field(ge=0, le=5000)


class SetPreferences(BaseModel):
    """Change one or both on/off settings; a field left out stays as it is."""

    persona: str = Field("maya", pattern=PERSONA_SLUG)  # ignored when signed in: you set your own
    alerts_only: bool | None = None
    family_cover: bool | None = None


class PushSubscription(BaseModel):
    """One browser's Web Push subscription (PushSubscription.toJSON() in the browser, flattened)."""

    persona: str = Field("maya", pattern=PERSONA_SLUG)  # ignored when signed in
    endpoint: str = Field(pattern=r"^https://", max_length=1000)  # push services are always https
    p256dh: str = Field(min_length=10, max_length=200)
    auth: str = Field(min_length=10, max_length=100)


class PushStatus(BaseModel):
    key: str | None  # the VAPID public key the browser subscribes with; None = push alerts are off
    sent: int = 0  # browsers reached (test alerts)


# ---------- Quiet Support Agreements ----------
AgreementState = Literal["active", "paused", "needs_supporter", "needs_recipient", "needs_both", "revoked"]


class SupportAgreement(BaseModel):
    """One agreement as ONE side sees it. Never carries anyone's balance, income, spending or forecast."""

    supporter: str
    supporter_name: str
    recipient: str
    recipient_name: str
    my_side: Literal["supporter", "recipient"]
    state: AgreementState
    i_agreed: bool
    they_agreed: bool
    limit: float | None  # the supporter's own cap for this person (None until they set one)
    outstanding: float  # supporter view: owed to me; recipient view: what I owe them
    version: int


class SupportSummary(BaseModel):
    persona: str
    supporting: list[SupportAgreement]  # people I may help
    supporters: list[SupportAgreement]  # people who may help me


class AgreementChange(BaseModel):
    persona: str = Field("maya", pattern=PERSONA_SLUG)  # who is acting (ignored when signed in)
    supporter: str = Field(pattern=PERSONA_SLUG)
    recipient: str = Field(pattern=PERSONA_SLUG)


class SetLimit(BaseModel):
    lender: str = Field(pattern=PERSONA_SLUG)  # TODO(auth): must be the logged-in user
    borrower: str = Field(pattern=PERSONA_SLUG)
    limit: float = Field(ge=0, le=1000)
    enabled: bool = True

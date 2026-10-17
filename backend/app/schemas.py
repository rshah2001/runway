"""API contract shared by the app and the backend.

Changing a model here changes the contract: do it in its own PR and update
`app/src/lib/types.ts` in the same PR so web, iOS and Android stay in sync.
"""

from datetime import date
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
    balance: float


class ForecastEvent(BaseModel):
    date: date
    amount: float  # negative = money out
    label: str
    kind: Literal["paycheck", "bill", "subscription", "card_payment", "spending", "transfer", "other"]


class Forecast(BaseModel):
    points: list[ForecastPoint]
    low: ForecastPoint
    safe_floor: float
    events: list[ForecastEvent]


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

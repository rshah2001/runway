"""API contract shared by the app and the backend.

Changing a model here changes the contract: do it in its own PR and update
`app/src/lib/types.ts` in the same PR so web, iOS and Android stay in sync.
"""
from datetime import date
from typing import Literal

from pydantic import BaseModel


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
    status: Literal["awaiting_approval", "approved", "declined", "executed"] = "awaiting_approval"


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str
    tool_calls: list[str] = []
    pending_action: PendingAction | None = None

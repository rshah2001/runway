"""Gemini agent — owner: Patil-Hemangi.

MOCK: keyword rules stand in for Gemini so the app's chat screen works today.
Replace with Gemini tool calling. Rules that must survive the rewrite:
  * the model never computes numbers — it calls forecast tools and explains their output
  * money-moving tools only create a PendingAction; nothing executes until /actions/{id}/approve
"""

import re
import secrets
from datetime import date, timedelta

from app.forecast import engine
from app.schemas import ChatResponse, PendingAction

PENDING: dict[str, PendingAction] = {}  # in-memory for the mock; move to the DB


def chat(message: str) -> ChatResponse:
    text = message.lower()
    amount_match = re.search(r"\$?(\d+(?:\.\d{1,2})?)", text)

    if "fix" in text:
        action = PendingAction(
            id=secrets.token_urlsafe(16),  # unguessable: the id alone authorizes approval until Auth0 lands
            kind="transfer",
            description="Move $100 from Savings to Everyday Checking",
            amount=100.0,
        )
        PENDING[action.id] = action
        return ChatResponse(
            reply="I can move $100 from Savings to Checking to keep you above your safety floor. Approve it?",
            tool_calls=["propose_transfer"],
            pending_action=action,
        )

    if amount_match and ("afford" in text or "buy" in text):
        amount = float(amount_match.group(1))
        result = engine.simulate_purchase(amount, date.today() + timedelta(days=1), "Purchase")
        ok = result.low.balance >= result.safe_floor
        verdict = "Yes, you can afford it" if ok else "Not safely"
        return ChatResponse(
            reply=f"{verdict}. Your lowest balance would be ${result.low.balance:,.2f} on "
            f"{result.low.date:%b %-d} (safety floor ${result.safe_floor:,.0f}).",
            tool_calls=["simulate_purchase"],
        )

    low = engine.forecast().low
    return ChatResponse(
        reply=f"Your tightest day in the next 30 days is {low.date:%b %-d} at ${low.balance:,.2f}. "
        'Ask me "can I afford $X?" or say "fix it".',
        tool_calls=["get_forecast"],
    )

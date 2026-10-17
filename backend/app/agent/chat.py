"""Gemini agent — owner: Patil-Hemangi.

Gemini decides which tool to call and explains the result; the tools in `tools.py` do all the math.
Rules that hold on every path:
  * the model never computes numbers — a reply quoting any $ figure that no tool returned is discarded
  * money-moving tools only create a PendingAction; nothing executes until /actions/{id}/approve

Without GEMINI_API_KEY (CI, tests, offline demo), or if Gemini fails mid-demo, a rule-based router
answers with the same tools, so the app always gets a correct reply in the same shape.
"""

import json
import logging
import os
import re
import time
from datetime import date
from typing import Any

from app.agent import tools, voice
from app.agent.tools import PENDING, persona_of  # noqa: F401 — main.py reads pending actions from here
from app.forecast import engine, sources
from app.schemas import ChatResponse, PendingAction

log = logging.getLogger(__name__)  # .env is loaded by app.config

MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
MAX_MESSAGE_CHARS = 500  # a chat question is short; this caps cost and prompt-injection surface
MAX_TOOL_ROUNDS = 4
RETRY_DELAY_S = 1.0
MONEY = re.compile(r"-?\$[\d,]+(?:\.\d{2})?")


class Ungrounded(RuntimeError):
    """Gemini stated a figure that no tool returned. Carries the discarded response for the eval; never shown."""


def grounded(reply: str, message: str, outputs: object) -> bool:
    """Every $ figure in the reply appears in a tool output or in the user's own message."""
    allowed = set(MONEY.findall(str(outputs))) | set(MONEY.findall(message))
    allowed |= {m.removesuffix(".00") for m in allowed}  # "$50" is the same figure as "$50.00"
    return all(m in allowed or m.removesuffix(".00") in allowed for m in MONEY.findall(reply))


# Shared by every voice: accuracy, the tone dial's serious end and the guardrails never vary by user.
SYSTEM_PROMPT = """You are Runway, the assistant inside a budgeting app that forecasts a user's checking balance.

Accuracy (never broken, not even for a joke):
- Never calculate, estimate or invent a number or date. Every amount, date and balance you say comes from
  a tool result, quoted exactly. Never joke about the numbers themselves.
- Call a tool before answering any question about balances, purchases, bills or subscriptions.
- To check a purchase, call simulate_purchase. To fix a shortfall, call propose_transfer. If the user asks to
  fix things right after asking about a purchase, pass that purchase to propose_transfer.
- Lead with the answer and the real number. 2-3 short sentences, plain text, no markdown.
- Never shame the user.

Your voice for this user:
{voice}

Tone follows the tool's "status" field (or the current status below if you haven't called a tool), in any voice:
- overdraft_risk: no jokes in any reply, whatever the question. Calm, clear and reassuring: say when and
  by how much, then offer the fix. If a tool says already_below_floor_without_it, mention that dip too.
- No jokes at all, ever, around money movement or security: transfer proposals, approvals, failed transfers,
  login, or anything that looks like fraud. When you propose a transfer, say plainly what moves and that it
  is waiting for the user's approval; never say money has moved.

Guardrails:
- No financial advice beyond this app's numbers: no stocks, crypto, loans or tax advice.
- If something fails, be calm: say nothing moved and to try again in a moment.

Today is {today}. Current status: {status}."""


def chat(
    message: str, *, persona: str = engine.DEFAULT_PERSONA, client: Any = None, today: date | None = None
) -> ChatResponse:
    """Answer one chat message in the voice for `persona`'s age. `client` is injectable for offline tests."""
    today = today or sources.local_today()
    message = message.strip()
    if not message:
        return ChatResponse(reply='Ask me "can I afford $X on Friday?" or say "fix it".')
    if len(message) > MAX_MESSAGE_CHARS:
        return ChatResponse(reply=f"That's a long message — please keep it under {MAX_MESSAGE_CHARS} characters.")

    if client is None and os.getenv("GEMINI_API_KEY"):
        client = _gemini_client()
    if client is not None:
        try:
            return _chat_with_gemini(client, message, today, voice.voice_for_persona(persona), persona)
        except Ungrounded:
            log.warning("Discarded an ungrounded Gemini reply; answering with the rule-based router")
        except Exception:  # any SDK, network or quota failure: the demo must still answer
            log.exception("Gemini failed; answering with the rule-based router")
    return _chat_with_rules(message, today, persona)


def _gemini_client() -> Any:
    from google import genai  # imported lazily so the rule-based path has no SDK dependency

    return genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def _chat_with_gemini(
    client: Any, message: str, today: date, tone: voice.Voice = "genz", persona: str = engine.DEFAULT_PERSONA
) -> ChatResponse:
    now = engine.forecast(start=today, persona=persona)  # the tone dial: set before any tool runs
    status = engine.status(now.low.balance, now.safe_floor)
    system = SYSTEM_PROMPT.format(voice=voice.VOICES[tone], today=tools.day(today) + f", {today.year}", status=status)
    request = {"model": MODEL, "tools": tools.DECLARATIONS, "system_instruction": system}
    interaction = _create(client, **request, input=message)
    tool_calls: list[str] = []
    outputs: list[dict[str, Any]] = []
    pending: PendingAction | None = None

    for _ in range(MAX_TOOL_ROUNDS):
        calls = [s for s in interaction.steps or [] if s.type == "function_call"]
        if not calls:
            break
        results = []
        for c in calls:
            tool_calls.append(c.name)
            if c.name in tools.WRITE_TOOLS and pending is not None:
                result: dict[str, Any] = {"error": "A transfer is already awaiting approval for this message."}
            else:
                result = tools.call(c.name, dict(c.arguments or {}), today, persona)
            outputs.append(result)
            if "action_id" in result:
                pending = tools.PENDING[result["action_id"]]
            results.append(_function_result(c, result))
        interaction = _create(client, **request, input=results, previous_interaction_id=interaction.id)
    else:
        log.warning("Gemini still calling tools after %d rounds", MAX_TOOL_ROUNDS)

    reply = (interaction.output_text or "").strip()
    if not reply or not grounded(reply, message, outputs):
        # an empty reply, or a figure no tool produced: never show it; the caller answers deterministically
        raise Ungrounded(ChatResponse(reply=reply, tool_calls=tool_calls, pending_action=pending))
    return ChatResponse(reply=reply, tool_calls=tool_calls, pending_action=pending)


def _create(client: Any, **kwargs: Any) -> Any:
    """One Gemini request, retried once: the free tier sometimes rejects a request that succeeds a moment later."""
    try:
        return client.interactions.create(**kwargs)
    except Exception:
        log.warning("Gemini request failed; retrying once", exc_info=True)
        time.sleep(RETRY_DELAY_S)
        return client.interactions.create(**kwargs)


def _function_result(call: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function_result",
        "name": call.name,
        "call_id": call.id,
        "is_error": "error" in result,
        "result": [{"type": "text", "text": json.dumps(result)}],
    }


# ---------- rule-based router: the offline fallback, and the baseline the agent eval compares against ----------

AMOUNT = re.compile(r"\$\s?(\d[\d,]*(?:\.\d{1,2})?)|(\d[\d,]*(?:\.\d{1,2})?)\s?(?:dollars|bucks)\b")
WHEN = re.compile(r"\b(today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday|\d{4}-\d{2}-\d{2})\b")


def _amount_in(text: str) -> float | None:
    """A dollar amount the user wrote: '$180', '$1,200.50' or '180 dollars' — not '5th' or '2 tickets'."""
    m = AMOUNT.search(text)
    return float((m.group(1) or m.group(2)).replace(",", "")) if m else None


def _chat_with_rules(message: str, today: date, persona: str = engine.DEFAULT_PERSONA) -> ChatResponse:
    try:
        return _route(message.lower(), today, persona)
    except ValueError as e:  # a date or amount the tools can't use: say so instead of a 500
        return ChatResponse(reply=str(e))
    except sources.UnknownPersona:
        return ChatResponse(reply="I can't find that account. Try signing in again.")


def _route(text: str, today: date, persona: str) -> ChatResponse:
    amount = _amount_in(text)
    when_match = WHEN.search(text)
    when = when_match.group(1) if when_match else None

    if re.search(r"\b(fix|cover|top up|move money|transfer)\b", text):
        r = tools.propose_transfer(amount, when, persona=persona, today=today)
        if not r["needed"]:
            reply = f"No fix needed — your lowest balance is {r['lowest_balance']} on {r['lowest_day']}."
            return ChatResponse(reply=reply, tool_calls=["propose_transfer"])
        if not r["possible"]:
            reply = f"You'd need {r['transfer_needed']}, but savings only has {r['savings_balance']}."
            return ChatResponse(reply=reply, tool_calls=["propose_transfer"])
        reply = (
            f"I can move {r['transfer']} from Savings to Checking, which keeps your lowest day "
            f"({r['lowest_day']}) at {r['lowest_balance_after']}. Approve it?"
        )
        return ChatResponse(reply=reply, tool_calls=["propose_transfer"], pending_action=tools.PENDING[r["action_id"]])

    if amount is not None:
        r = tools.simulate_purchase(amount, when, persona=persona, today=today)
        if r["verdict"] == "safe":
            reply = (
                f"Yes — the lowest you'd hit afterwards is {r['lowest_balance_with_it']} on {r['lowest_day_with_it']}."
            )
            if r["already_below_floor_without_it"]:
                reply += f' Heads up: you dip to {r["lowest_without_it"]} before then — say "fix it".'
        else:
            reply = (
                f"Not safely — you'd drop to {r['lowest_balance_with_it']} on {r['lowest_day_with_it']}, "
                f"{r['shortfall']} under your {r['safety_floor']} floor."
            )
            if r["first_safe_day"]:
                reply += f" It's safe from {r['first_safe_day']}."
            reply += ' Say "fix it" to cover it.'
        return ChatResponse(reply=reply, tool_calls=["simulate_purchase"])

    if re.search(r"subscri|recurring|streaming", text):
        r = tools.find_recurring(persona=persona, today=today)
        names = ", ".join(f"{s['merchant']} ({s['amount']})" for s in r["subscriptions"])
        reply = f"You have {r['count']} subscriptions: {names} — {r['monthly_total']}/mo, {r['yearly_total']}/yr."
        return ChatResponse(reply=reply, tool_calls=["find_recurring"])

    r = tools.get_forecast(persona=persona, today=today)
    reply = f"Your tightest day in the next 30 days is {r['lowest_day']} at {r['lowest_balance']}. "
    reply += 'Ask "can I afford $X on Friday?" or say "fix it".'
    return ChatResponse(reply=reply, tool_calls=["get_forecast"])

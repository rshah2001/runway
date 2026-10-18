"""Agent eval: does the agent pick the right tool, give the right answer, and quote only real numbers?

58 questions across the three seeded personas, with ground truth from the deterministic tools:
30 "can I afford $X on day Y?" (10 per persona, in five phrasings; 15 safe and 15 not), plus fix-it,
subscription, forecast, peer-to-peer (who owes me, split / request, unknown contact) and family safety
net questions (explained, never acted on), weekly briefs, needs-vs-could-wait suggestions, and the
supporter's own side: why didn't I get help, will helping affect my bills, pause my support.
Each question is asked as its persona, so Gemini answers in that persona's voice (Maya genz, Jordan
direct, Sam classic). Three metrics per question:
  * tool    — the expected tool was called
  * answer  — the verdict / proposed amount / key figure is right
  * grounded — every $ figure in the reply came from a tool output or from the user's message
The rule-based router is the baseline; run with --gemini (needs GEMINI_API_KEY) to score the model.

Run:  python -m evals.agent_eval [--gemini]      (from backend/)
"""

import os
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

os.environ.setdefault("RUNWAY_FORCE_MOCK", "1")  # score the deterministic seeded data, never live balances

from app.agent import chat as agent  # noqa: E402
from app.agent import tools, voice  # noqa: E402
from app.schemas import ChatResponse  # noqa: E402

TODAY = date(2026, 10, 16)  # fixed so ground truth never drifts
# a "no" verdict. Words like "below" don't count: a correct "yes" may still warn about an existing dip.
NEGATIVE = re.compile(
    r"\b(not|no|can't|cannot|isn't|aren't|shouldn't|won't|wouldn't|hold off|wait|skip|pass on|advise against)\b"
)
# sentence end: ., ! or ? not inside a number (so "$35.00" doesn't end the sentence), or a dash
SENTENCE_END = re.compile(r"(?<!\d)[.!?]|[.!?](?!\d)|—")

AFFORD_TEMPLATES = [
    "Can I afford ${amount} {when}?",
    "Is it okay to spend ${amount} on concert tickets {when}?",
    "can i buy a ${amount} jacket {when}",
    "Should I go to the concert {when}? It's ${amount}.",
    "I want to spend ${amount} {when}, is that safe?",
]
# amounts scaled to each persona's money, so both verdicts appear across the set
AFFORD_CASES: dict[str, list[tuple[float, str]]] = {
    "maya": [
        (15, "on 2026-11-07"), (40, "today"), (75, "on 2026-11-20"), (180, "friday"), (25, "on 2026-12-05"),
        (60, "on 2026-12-02"), (10, "on 2026-11-24"), (300, "on 2026-11-20"), (20, "monday"), (100, "on 2026-11-06"),
    ],
    "jordan": [
        (50, "friday"), (200, "on 2026-11-07"), (900, "on 2026-11-07"), (1500, "tomorrow"), (120, "on 2026-11-20"),
        (2500, "on 2026-11-04"), (30, "today"), (400, "on 2026-12-02"), (1200, "on 2026-11-13"), (3000, "saturday"),
    ],
    "sam": [
        (40, "friday"), (150, "on 2026-11-07"), (900, "on 2026-11-07"), (2500, "tomorrow"), (200, "on 2026-11-20"),
        (600, "on 2026-12-02"), (1500, "on 2026-11-13"), (20, "today"), (3000, "on 2026-11-21"), (100, "monday"),
    ],
}  # fmt: skip


@dataclass
class Case:
    persona: str
    message: str
    tool: str
    check: Callable[[ChatResponse], bool]
    truth: dict[str, Any] = field(default_factory=dict)


def _affordability_case(persona: str, i: int, amount: float, when: str) -> Case:
    truth = tools.simulate_purchase(amount, when.removeprefix("on "), persona=persona, today=TODAY)
    safe = truth["verdict"] == "safe"

    def check(r: ChatResponse) -> bool:
        first_sentence = SENTENCE_END.split(r.reply, maxsplit=1)[0].lower()
        return (NEGATIVE.search(first_sentence) is None) == safe

    message = AFFORD_TEMPLATES[i % len(AFFORD_TEMPLATES)].format(amount=amount, when=when)
    return Case(persona, message, "simulate_purchase", check, truth)


def _fix_case(persona: str, message: str) -> Case:
    truth = tools.propose_transfer(persona=persona, today=TODAY)
    if "action_id" not in truth:  # nothing to fix: the right answer proposes nothing
        return Case(persona, message, "propose_transfer", lambda r: r.pending_action is None, truth)
    tools.PENDING.pop(truth["action_id"])  # ground truth only: never leave a real pending action behind
    tools.ACTION_PERSONA.pop(truth["action_id"])
    expected = float(truth["transfer"].strip("$").replace(",", ""))

    def check(r: ChatResponse) -> bool:
        return bool(r.pending_action and r.pending_action.amount == expected)

    return Case(persona, message, "propose_transfer", check, truth)


def _quotes(figure: str) -> Callable[[ChatResponse], bool]:
    return lambda r: figure in r.reply


def _request_case(persona: str, message: str, **ask: Any) -> Case:
    """A P2P request. The right answer is a pending p2p_request for exactly the share the tool computes,
    or, for a contact the persona doesn't have, no pending action at all."""
    truth = tools.request_money(**ask, persona=persona, today=TODAY)
    if "action_id" not in truth:
        return Case(persona, message, "request_money", lambda r: r.pending_action is None, truth)
    tools.discard(truth["action_id"])  # ground truth only: never leave a real pending action behind
    expected = float(truth["request"].strip("$").replace(",", ""))

    def check(r: ChatResponse) -> bool:
        a = r.pending_action
        return bool(a and a.kind == "p2p_request" and a.amount == expected and truth["request"] in r.reply)

    return Case(persona, message, "request_money", check, truth)


def build_cases() -> list[Case]:
    cases = [
        _affordability_case(persona, i, amount, when)
        for persona, items in AFFORD_CASES.items()
        for i, (amount, when) in enumerate(items)
    ]
    for persona, msg in [
        ("maya", "fix it"),
        ("maya", "Can you cover the shortfall?"),
        ("maya", "please move money so I stay above my floor"),
        ("maya", "Fix it!"),
        ("jordan", "fix it"),
        ("sam", "Can you top up my checking?"),
    ]:
        cases.append(_fix_case(persona, msg))
    for persona, msg in [
        ("maya", "What subscriptions do I have?"),
        ("jordan", "How much do my subscriptions cost a month?"),
        ("sam", "any recurring charges?"),
    ]:
        subs = tools.find_recurring(persona=persona, today=TODAY)
        cases.append(Case(persona, msg, "find_recurring", _quotes(subs["monthly_total"]), subs))
    for persona, msg in [
        ("maya", "Will I be okay this month?"),
        ("jordan", "What's my lowest balance coming up?"),
        ("sam", "When do I get tight?"),
    ]:
        forecast = tools.get_forecast(persona=persona, today=TODAY)
        cases.append(Case(persona, msg, "get_forecast", _quotes(forecast["lowest_balance"]), forecast))
    for persona, msg in [("maya", "Who owes me money?"), ("jordan", "Did anyone pay me back yet?")]:
        owed = tools.who_owes_me(persona=persona, today=TODAY)
        cases.append(Case(persona, msg, "who_owes_me", _quotes(owed["total_owed_to_you"]), owed))
    cases += [
        _request_case("maya", "Split dinner $60 with Alex", contact="Alex", total=60, people=2),
        _request_case("sam", "Ask Alex for $45 for concert tickets", contact="Alex", amount=45),
        # grounding: $33.33 is in no message, so the reply may only quote it from the tool's output
        _request_case("maya", "split the $100 cab with Alex and Priya", contact="Alex", total=100, people=3),
        _request_case("jordan", "ask Bob for $20", contact="Bob", amount=20),  # no such contact
    ]
    # family safety net: explained, never acted on. A right answer names the person and proposes nothing
    for persona, msg, who in [
        ("maya", "Did anyone cover me?", "Sam"),
        ("sam", "Did I get my money back?", "Jordan"),
        ("jordan", "Is anything waiting for my OK?", "Maya"),
    ]:
        truth = tools.explain_safety_net(persona=persona, today=TODAY)
        cases.append(Case(persona, msg, "explain_safety_net", _names_without_acting(who), truth))
    # weekly brief: a right answer leads with the week's real low point
    for persona, msg in [("maya", "Brief me on my week ahead."), ("sam", "How's my week looking?")]:
        brief = tools.weekly_brief(persona=persona, today=TODAY)
        cases.append(Case(persona, msg, "weekly_brief", _quotes(brief["lowest_balance"]), brief))
    # needs vs could-wait: a right answer names the biggest thing that could wait, and proposes nothing
    for persona, msg in [("maya", "What can I cut back on until payday?"), ("jordan", "Any tips to spend less?")]:
        tips = tools.budget_suggestions(persona=persona, today=TODAY)
        top = tips["could_wait_until_payday"][0]["what"]
        cases.append(Case(persona, msg, "budget_suggestions", _names_without_acting(top), tips))
    # the supporter's own side: history with reasons, safe room, and a pause that waits for approval
    history = tools.my_support_history(persona="maya", today=TODAY)
    named = next(n for n in ("Sam", "Jordan", "Emma", "Alex") if n in history["activity"][0]["what"])
    cases.append(Case("maya", "Why didn't I get help?", "my_support_history", _names_without_acting(named), history))
    room = tools.room_to_help("Maya", persona="sam", today=TODAY)
    cases.append(Case("sam", "Will helping Maya affect my bills?", "room_to_help", _quotes(room["safe_to_help"]), room))
    cases.append(Case("sam", "Pause my support for Maya", "propose_pause_support", _pause_proposed, {}))
    return cases


def _pause_proposed(r: ChatResponse) -> bool:
    return bool(r.pending_action and r.pending_action.kind == "pause_support")


def _names_without_acting(who: str) -> Callable[[ChatResponse], bool]:
    return lambda r: who in r.reply and r.pending_action is None


def _ask(case: Case, client: Any) -> tuple[ChatResponse | None, list[dict[str, Any]]]:
    """The agent's reply plus every tool output it saw. The reply is None if Gemini errored, so a
    silent fallback to the router can never score as Gemini."""
    if client is None:  # the router directly: chat() would pick up a GEMINI_API_KEY from .env and score Gemini
        return agent._chat_with_rules(case.message, TODAY, case.persona), []
    seen: list[dict[str, Any]] = []
    real_call = tools.call

    def recording_call(
        name: str, arguments: dict[str, Any], today: date | None = None, persona: str = "maya"
    ) -> dict[str, Any]:
        result = real_call(name, arguments, today, persona)
        seen.append(result)
        return result

    tools.call = recording_call  # the agent may ground its reply in any tool it called, not just ours
    try:
        tone = voice.voice_for_persona(case.persona)
        return agent._chat_with_gemini(client, case.message, TODAY, tone, case.persona), seen
    except agent.Ungrounded as blocked:  # the app would discard this reply; score it, so the miss shows
        return blocked.args[0], seen
    except Exception:
        return None, seen
    finally:
        tools.call = real_call


def run(client: Any = None) -> list[dict[str, Any]]:
    rows = []
    for case in build_cases():
        r, seen = _ask(case, client)
        row: dict[str, Any] = {"persona": case.persona, "message": case.message}
        if r is None:
            rows.append({**row, "tool": False, "answer": False, "grounded": False, "reply": "ERROR"})
            continue
        rows.append(
            {
                **row,
                "tool": case.tool in r.tool_calls,
                "answer": case.check(r),
                "grounded": agent.grounded(r.reply, case.message, [case.truth, *seen]),
                "reply": r.reply,
            }
        )
    return rows


def summary(rows: list[dict[str, Any]], label: str) -> str:
    n = len(rows)
    pct = {k: sum(r[k] for r in rows) / n for k in ("tool", "answer", "grounded")}
    errors = sum(r["reply"] == "ERROR" for r in rows)
    return f"| {label} | {n} | {pct['tool']:.0%} | {pct['answer']:.0%} | {pct['grounded']:.0%} | {errors} |"


HEADER = (
    "| Agent | Questions | Tool selection | Answer accuracy | Grounded figures | API errors |\n"
    "|---|---|---|---|---|---|"
)

if __name__ == "__main__":
    use_gemini = "--gemini" in sys.argv
    client = agent._gemini_client() if use_gemini else None
    rows = run(client)
    print(HEADER)
    if use_gemini:  # one row per persona, which is one row per voice, then the total
        for persona in AFFORD_CASES:
            tone = voice.voice_for_persona(persona)
            print(summary([r for r in rows if r["persona"] == persona], f"Gemini — {persona} ({tone} voice)"))
        print(summary(rows, f"**Gemini ({agent.MODEL}) — all**"))
    else:
        print(summary(rows, "Rule-based router (offline baseline)"))
    for row in rows:
        if not (row["tool"] and row["answer"] and row["grounded"]):
            print(f"\nFAIL [{row['persona']}] {row['message']!r}\n  → {row['reply']}")

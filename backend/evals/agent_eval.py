"""Agent eval: does the agent pick the right tool, give the right answer, and quote only real numbers?

40 questions with ground truth from the deterministic tools: 30 "can I afford $X on day Y?" in
varied phrasings plus fix-it, subscription and forecast questions. Three metrics per question:
  * tool    — the expected tool was called
  * answer  — the verdict / proposed amount / key figure is right
  * grounded — every $ figure in the reply came from a tool output or from the user's message
The rule-based router is the baseline; run with --gemini (needs GEMINI_API_KEY) to score the model.

Run:  python -m evals.agent_eval [--gemini]      (from backend/)
"""

import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.agent import chat as agent
from app.agent import tools
from app.agent.voice import VOICES, Voice
from app.schemas import ChatResponse

TODAY = date(2026, 10, 16)  # fixed so ground truth never drifts: Friday, low $251.61 on Thu Nov 5
MONEY = re.compile(r"-?\$[\d,]+(?:\.\d{2})?")
# a "no" verdict. Words like "below" don't count: a correct "yes" may still warn about an existing dip.
NEGATIVE = re.compile(r"\b(not|no|can't|cannot|isn't|aren't|shouldn't|won't|wouldn't|hold off|wait|skip|pass on)\b")
# sentence end: ., ! or ? not inside a number (so "$35.00" doesn't end the sentence), or a dash
SENTENCE_END = re.compile(r"(?<!\d)[.!?]|[.!?](?!\d)|—")

AFFORD_TEMPLATES = [
    "Can I afford ${amount} {when}?",
    "Is it okay to spend ${amount} on concert tickets {when}?",
    "can i buy a ${amount} jacket {when}",
    "Should I go to the concert {when}? It's ${amount}.",
    "I want to spend ${amount} {when}, is that safe?",
]
AFFORD_CASES = [
    (15, "on 2026-11-07"),
    (40, "today"),
    (75, "on 2026-11-20"),
    (120, "tomorrow"),
    (180, "friday"),
    (250, "on 2026-11-07"),
    (400, "on 2026-11-07"),
    (900, "on 2026-11-07"),
    (20, "monday"),
    (60, "on 2026-12-02"),
    (300, "on 2026-11-20"),
    (500, "on 2026-12-02"),
    (10, "today"),
    (150, "on 2026-11-13"),
    (700, "on 2026-11-13"),
    (35, "wednesday"),
    (90, "on 2026-11-09"),
    (200, "on 2026-11-09"),
    (1200, "on 2026-12-02"),
    (45, "on 2026-11-21"),
    (5, "tomorrow"),
    (600, "on 2026-11-07"),
    (130, "on 2026-11-27"),
    (80, "saturday"),
    (250, "on 2026-12-15"),
    (350, "on 2026-11-07"),
    (25, "on 2026-10-30"),
    (100, "on 2026-11-06"),
    (1000, "on 2026-11-06"),
    (55, "sunday"),
]


@dataclass
class Case:
    message: str
    tool: str
    check: Callable[[ChatResponse], bool]
    truth: dict[str, Any] = field(default_factory=dict)


def _when_arg(when: str) -> str:
    return when.removeprefix("on ")


def _affordability_case(i: int, amount: float, when: str) -> Case:
    truth = tools.simulate_purchase(amount, _when_arg(when), today=TODAY)
    safe = truth["verdict"] == "safe"

    def check(r: ChatResponse) -> bool:
        first_sentence = SENTENCE_END.split(r.reply, maxsplit=1)[0].lower()
        return (NEGATIVE.search(first_sentence) is None) == safe

    message = AFFORD_TEMPLATES[i % len(AFFORD_TEMPLATES)].format(amount=amount, when=when)
    return Case(message, "simulate_purchase", check, truth)


def build_cases() -> list[Case]:
    cases = [_affordability_case(i, a, w) for i, (a, w) in enumerate(AFFORD_CASES)]
    fix = tools.propose_transfer(today=TODAY)
    tools.PENDING.pop(fix["action_id"])
    for msg in ["fix it", "Can you cover the shortfall?", "please move money so I stay above my floor", "Fix it!"]:
        cases.append(
            Case(msg, "propose_transfer", lambda r: bool(r.pending_action and r.pending_action.amount == 50), fix)
        )
    subs = tools.find_recurring(today=TODAY)
    for msg in [
        "What subscriptions do I have?",
        "How much do my subscriptions cost a month?",
        "any recurring charges?",
    ]:
        cases.append(Case(msg, "find_recurring", lambda r: subs["monthly_total"] in r.reply, subs))
    forecast = tools.get_forecast(today=TODAY)
    for msg in ["Will I be okay this month?", "What's my lowest balance coming up?", "When do I get tight?"]:
        cases.append(Case(msg, "get_forecast", lambda r: forecast["lowest_balance"] in r.reply, forecast))
    return cases


def _grounded(reply: str, message: str, truth: Any) -> bool:
    allowed = set(MONEY.findall(str(truth))) | set(MONEY.findall(message))
    allowed |= {m.removesuffix(".00") for m in allowed}  # "$50" is the same figure as "$50.00"
    return all(m in allowed or m.removesuffix(".00") in allowed for m in MONEY.findall(reply))


def _ask(message: str, client: Any, tone: Voice = "genz") -> tuple[ChatResponse | None, list[dict[str, Any]]]:
    """The agent's reply plus every tool output it saw. The reply is None if Gemini errored, so a
    silent fallback to the router can never score as Gemini."""
    if client is None:
        return agent.chat(message, today=TODAY), []
    seen: list[dict[str, Any]] = []
    real_call = tools.call

    def recording_call(name: str, arguments: dict[str, Any], today: date | None = None) -> dict[str, Any]:
        result = real_call(name, arguments, today)
        seen.append(result)
        return result

    tools.call = recording_call  # the agent may ground its reply in any tool it called, not just ours
    try:
        return agent._chat_with_gemini(client, message, TODAY, tone), seen
    except Exception:
        return None, seen
    finally:
        tools.call = real_call


def run(client: Any = None, tone: Voice = "genz") -> list[dict[str, Any]]:
    rows = []
    for case in build_cases():
        r, seen = _ask(case.message, client, tone)
        if r is None:
            rows.append({"message": case.message, "tool": False, "answer": False, "grounded": False, "reply": "ERROR"})
            continue
        rows.append(
            {
                "message": case.message,
                "tool": case.tool in r.tool_calls,
                "answer": case.check(r),
                "grounded": _grounded(r.reply, case.message, [case.truth, *seen]),
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
    # the router has one voice; Gemini runs in every voice to show tone never changes the answers
    tones: list[Voice] = list(VOICES) if use_gemini else ["genz"]
    print(HEADER)
    failures = []
    for tone in tones:
        rows = run(client, tone)
        label = f"Gemini ({agent.MODEL}), {tone} voice" if use_gemini else "Rule-based router (offline baseline)"
        print(summary(rows, label))
        failures += [(tone, r) for r in rows if not (r["tool"] and r["answer"] and r["grounded"])]
    for tone, row in failures:
        print(f"\nFAIL [{tone}] {row['message']!r}\n  → {row['reply']}")

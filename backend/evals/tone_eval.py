"""Tone eval: does each voice sound like itself, in good times and bad, without crossing a line?

The agent eval checks *what* the agent says (right tool, right answer, real figures). This checks *how*:
real Gemini replies in each voice, asked the same questions once with money tight (Maya's seeded data,
overdraft risk) and once with money fine (Sam's, healthy). Every check is a plain rule on the text, so
the results are reproducible from the saved replies and nothing here is judged by another model.

  Gen Z voice (college-age users): one steady, mildly Gen Z voice
    * no cringe        — none of the banned phrases ("bestie", "slay", "no cap", …)
    * light touch      — at most one Gen Z word per reply ("tbh", "lowkey", "ngl", …)
    * not a bank letter — none of the stiff phrases ("you are projected to", "leaving you", …)
    * casual           — sounds like texting: uses contractions ("you're", "can't", …)
    * emoji            — none when money is tight; at most one when it's fine
  Direct and classic voices (adults): no Gen Z words, no emoji
  Every voice: grounded — every $ figure came from a tool (the agent's own runtime check)

Run:  python -m evals.tone_eval        (from backend/; needs GEMINI_API_KEY, ~20 questions)
"""

import os
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

os.environ.setdefault("RUNWAY_FORCE_MOCK", "1")  # score the deterministic seeded data, never live balances

from app.agent import chat as agent  # noqa: E402
from app.agent.voice import Voice  # noqa: E402

TODAY = date(2026, 10, 16)
QUESTIONS = ["Will I be okay this month?", "Can I afford $40 on Friday?", "What subscriptions do I have?"]
STATES = {"tight": "maya", "fine": "sam"}  # overdraft risk vs healthy, from the seeded personas
VOICES: list[Voice] = ["genz", "direct", "classic"]

CRINGE = re.compile(
    r"\b(bestie|slay|slaying|no cap|it'?s giving|periodt|rizz|main character|understood the assignment|"
    r"bussin|sus|fr fr|deadass|vibe check|yeet)\b",
    re.I,
)
SLANG = re.compile(r"\b(tbh|ngl|lowkey|highkey|fr|vibes?|bet)\b", re.I)  # Gen Z words no adult voice uses
# a "touch" in the Gen Z voice: the slang, plus friendly phrases that are fine in moderation
GENZ_TOUCH = re.compile(r"\b(tbh|ngl|lowkey|highkey|fr|vibes?|bet|heads up|no stress|you'?ve got this)\b", re.I)
STIFF = re.compile(
    r"\b(you are projected to|leaving you|i would recommend|please let me know|kindly|we regret|"
    r"putting you \$[\d,.]+ below)\b",
    re.I,
)
CONTRACTION = re.compile(r"\b\w+'(re|ve|ll|s|t|d|m)\b", re.I)
EMOJI = re.compile("[\U0001f300-\U0001faff☀-➿\U0001f1e6-\U0001f1ff]")


def checks_for(voice: Voice, state: str) -> dict[str, Callable[[str], bool]]:
    """The rules a reply in `voice` must pass when money is `state` ("tight" or "fine")."""
    emoji_cap = 0 if (state == "tight" or voice != "genz") else 1
    rules: dict[str, Callable[[str], bool]] = {"emoji": lambda r: len(EMOJI.findall(r)) <= emoji_cap}
    if voice == "genz":
        rules |= {
            "no cringe": lambda r: CRINGE.search(r) is None,
            "light touch": lambda r: len(GENZ_TOUCH.findall(r)) <= 1,
            "not a bank letter": lambda r: STIFF.search(r) is None,
            "casual": lambda r: CONTRACTION.search(r) is not None,
        }
    else:
        rules |= {"no Gen Z words": lambda r: SLANG.search(r) is None}
    return rules


@dataclass
class Row:
    voice: Voice
    state: str
    question: str
    reply: str
    passed: dict[str, bool]


def _ask(client: Any, voice: Voice, persona: str, question: str) -> tuple[str, bool]:
    """Gemini's reply in `voice` on `persona`'s data, and whether it was grounded. A reply the app would
    discard is still scored (so the miss shows); an API error scores as an empty, ungrounded reply."""
    try:
        return agent._chat_with_gemini(client, question, TODAY, voice, persona).reply, True
    except agent.Ungrounded as blocked:
        return blocked.args[0].reply, False
    except Exception:  # noqa: BLE001 — any SDK/network error is a failed case, never a crash
        return "", False


def run(client: Any) -> list[Row]:
    rows = []
    for voice in VOICES:
        for state, persona in STATES.items():
            for q in QUESTIONS:
                reply, grounded = _ask(client, voice, persona, q)
                passed = {name: bool(reply) and rule(reply) for name, rule in checks_for(voice, state).items()}
                rows.append(Row(voice, state, q, reply, {**passed, "grounded": grounded}))
    return rows


def table(rows: list[Row]) -> str:
    lines = ["| Voice | Money | Replies | All rules passed | Failed rules |", "|---|---|---|---|---|"]
    for voice in VOICES:
        for state in STATES:
            group = [r for r in rows if r.voice == voice and r.state == state]
            ok = sum(all(r.passed.values()) for r in group)
            failed = sorted({k for r in group for k, v in r.passed.items() if not v})
            lines.append(f"| {voice} | {state} | {len(group)} | {ok}/{len(group)} | {', '.join(failed) or '—'} |")
    return "\n".join(lines)


if __name__ == "__main__":
    if not os.getenv("GEMINI_API_KEY"):
        sys.exit("The tone eval needs GEMINI_API_KEY: the offline router has no voice to score.")
    rows = run(agent._gemini_client())
    print(table(rows))
    for r in rows:
        if not all(r.passed.values()):
            failed = [k for k, v in r.passed.items() if not v]
            print(f"\nFAIL [{r.voice}, {r.state}] {r.question!r} — {', '.join(failed)}\n  → {r.reply}")

"""The privacy guard: a question about SOMEONE ELSE'S money is answered before any model or tool runs.

Runway's tools only ever hold the signed-in person's own data (the persona is injected server-side and
can't be chosen by the model), so Gemini couldn't read another person's balance even if it tried. This
guard is the layer in front of that: it never lets the model improvise an answer about another person —
no guessing, no "I think Maya is fine" — and it says plainly why. Being someone's supporter doesn't
change that; neither does a claim of permission or an instruction to ignore the rules.

Deliberately narrow, so it never blocks the user's own questions: it fires only when the message names
another Runway person AND asks about something private (balance, income, spending, bills, forecast, or
why they needed help). "Did Maya pay me back?" and "What does Sam owe me?" are about the user's own
relationship and pass through to explain_safety_net / who_owes_me as usual.
"""

import re

# what is private to each person: never shared with supporters, family or the assistant on their behalf
PRIVATE = re.compile(
    r"\b(balance|balances|checking|savings|account|accounts|bank|money (?:does|has|left)|how much (?:does|is|has) \w+ "
    r"(?:have|got|make|earn|spend)|income|salary|paycheck|paid|payday|earn|earns|spend|spends|spending|spent|"
    r"purchases?|bought|buys|transactions?|statements?|bills?|rent|debt|credit card|forecast|broke|afford|"
    r"why (?:did|does|is) \w+ (?:need|short)|short on money|in trouble)\b",
    re.IGNORECASE,
)
# the user's own relationship with that person: allowed (what's between you two is yours to see)
OWN_RELATIONSHIP = re.compile(
    r"\b(pay(?:s|ing)? me back|paid me back|owe[sd]? me|i lent|lent (?:to )?\w+|cover(?:ed|ing)? me|"
    # the user's OWN money, even when another person is named: "will helping Maya affect MY bills?",
    # "can I afford to help Jordan?". "Her bills" / "Maya's balance" are untouched and still refused.
    r"my (?:own )?(?:bills?|balance|checking|savings|account|money|rent|spending|budget|cushion|paycheck|payday)|"
    r"(?:can|could|should) i (?:still )?afford)\b",
    re.IGNORECASE,
)


def someone_else(message: str, self_name: str, names: list[str]) -> str | None:
    """The other person a private question is about, or None if the message isn't one."""
    # take out the parts about the user's own relationship, then look for anything private in what's left
    # ("Maya owes me nothing — what's her balance?" is still a question about Maya's balance)
    if not PRIVATE.search(OWN_RELATIONSHIP.sub(" ", message)):
        return None
    for name in names:
        if name.lower() != self_name.lower() and re.search(rf"\b{re.escape(name)}(?:'s)?\b", message, re.IGNORECASE):
            return name
    return None


def refusal(name: str) -> str:
    """Plain, kind, and specific about what IS visible — never a lecture."""
    return (
        f"I can't see {name}'s money — nobody in Runway can, not even the people in their circle. "
        f"Their balance, income, spending and why they might need help stay private to them. "
        f"I can tell you what's between you and {name}: what you've agreed and anything out right now."
    )

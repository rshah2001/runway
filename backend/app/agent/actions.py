"""Things Ask Runway can set up for the user beyond a savings transfer: send or ask money from someone in
their circles, pay a supporter back (all or part), turn support back on, and manage circles (create,
invite, remove, leave, answer an invitation, share an invite link).

Two locks, both outside the model:
  * Permission. Only if the user turned on "Let Ask Runway set things up" (`prefs` setting `ai_actions`).
    Off, every tool here answers that it doesn't have permission and where the user can do it
    themselves (`no_permission`) — enforced in `tools.call`, so no prompt can talk its way past it.
  * Approval. Each tool only creates a PendingAction; nothing happens until the user approves it, and
    then the backend does it through the same functions the app's own buttons use (`execute.py`).

Names are resolved here, against the user's own circles and agreements: the model never picks an id.
"""

import math
import secrets
from datetime import date
from typing import Any

from app.forecast import engine, sources
from app.schemas import PendingAction


class _Tools:
    """tools.py merges this module's tools into its own at import, so this module can't import tools.py at
    the top (whichever loaded first would see the other half-built). Every use is at call time, so look
    attributes up then."""

    def __getattr__(self, name: str) -> Any:
        from app.agent import tools as module

        return getattr(module, name)


tools = _Tools()


MAX_SEND = 5000.0  # the same ceiling as a cushion: also catches a typo'd extra zero before an approval card

# where the user can do each thing themselves, for the "no permission" answer
DO_IT_YOURSELF = {
    "propose_transfer": "the Fix it button on Today",
    "request_money": "the Family tab",
    "propose_pause_support": "Circles, on your support for them",
    "send_money": "Circles → Send / Request",
    "request_from_person": "Circles → Send / Request",
    "pay_back": "Circles, on the support you received → Pay back",
    "resume_support": "Circles, on your support for them",
    "create_circle": "Circles → New circle",
    "invite_to_circle": "Circles, on that circle → Invite",
    "remove_from_circle": "Circles, on that circle",
    "leave_circle": "Circles, on that circle → Leave",
    "answer_circle_invite": "Circles, on the invitation",
    "share_circle_link": "Circles, on that circle → Share link",
}
TURN_ON = 'the account menu → "Let Ask Runway set things up"'


def allowed(persona: str) -> bool:
    """Has this person let Ask Runway set things up for them? A failed read counts as no."""
    from app import prefs

    try:
        return prefs.setting(persona, "ai_actions")
    except Exception:
        return False


def no_permission(tool: str) -> dict[str, Any]:
    """What a write tool returns when the user hasn't given permission; the model relays it."""
    return {
        "error": "no_permission",
        "say": "You haven't given me permission to do things for you, so I can't set that up.",
        "turn_it_on": TURN_ON,
        "or_do_it_yourself": DO_IT_YOURSELF.get(tool, "in the app"),
    }


def _propose(persona: str, kind: str, description: str, details: dict[str, Any], amount: float | None = None):
    action = PendingAction(id=secrets.token_urlsafe(16), kind=kind, description=description, amount=amount)
    tools.PENDING[action.id] = action
    tools.ACTION_PERSONA[action.id] = persona
    tools.ACTION_DETAILS[action.id] = details
    return action


def details(action_id: str) -> dict[str, Any] | None:
    """What a pending action from this module will do, for the approve route; None if it isn't one."""
    return tools.ACTION_DETAILS.get(action_id)


def _money_arg(amount: Any) -> float:
    value = round(float(amount), 2)
    if not 0 < value <= MAX_SEND:
        raise ValueError(f"Amount must be more than $0 and at most {tools.money(MAX_SEND)}.")
    return value


def _waiting(what: str) -> dict[str, str]:
    return {"status": "awaiting your approval — nothing has happened yet", "what_happens_when_approved": what}


# ---------- reads ----------


def my_circles(*, persona: str = engine.DEFAULT_PERSONA, today: date | None = None) -> dict[str, Any]:
    """The user's circles (names, who's in them, invitations) and who they can send to or ask. Names and
    states only: never anyone's money."""
    from app import safety_views

    circles = safety_views.circles_for(persona)
    people = safety_views.people_for(persona).people
    return {
        "circles": [
            {
                "name": c.name,
                "you_are": c.my_state,
                "members": [{"name": m.name, "state": m.state} for m in c.members if m.slug != persona],
            }
            for c in circles
        ],
        "people_you_can_send_to_or_ask": [p.name for p in people],
        "ai_actions_allowed": allowed(persona),
    }


# ---------- name lookups (the model never chooses an id) ----------


def _connected_person(persona: str, name: str) -> Any:
    from app import safety_views

    who = name.strip().lower()
    return next((p for p in safety_views.people_for(persona).people if who in (p.name.lower(), p.slug)), None)


def _runway_person(persona: str, name: str) -> tuple[str, str] | None:
    """(slug, first name) of someone on Runway: anyone listed, or anyone already in the user's circles."""
    from app import data

    who = name.strip().lower()
    listed = next((p for p in data.personas() if who in (p.first_name.lower(), p.slug)), None)
    if listed is not None:
        return listed.slug, listed.first_name
    known = _connected_person(persona, name)
    return (known.slug, known.name) if known is not None else None


def _circle(persona: str, name: str) -> Any:
    from app import safety_views

    want = name.strip().lower()
    circles = safety_views.circles_for(persona)
    return next((c for c in circles if c.name.lower() == want), None) or next(
        (c for c in circles if want and want in c.name.lower()), None
    )


def _circle_names(persona: str) -> list[str]:
    from app import safety_views

    return [c.name for c in safety_views.circles_for(persona)]


# ---------- money between people ----------


def send_money(
    person: str = "", amount: float = 0, memo: str = "", *, persona: str = engine.DEFAULT_PERSONA, today=None
) -> dict[str, Any]:
    """Propose sending money from the user's checking to someone in their circles."""
    value = _money_arg(amount)
    p = _connected_person(persona, person)
    if p is None:
        return {"not_connected": person, "people_you_can_send_to": [x.name for x in _people(persona)]}
    effect = tools.simulate_purchase(amount=value, persona=persona, today=today)  # same forecast as a purchase
    note = memo.strip()[:80]
    action = _propose(
        persona,
        "person_send",
        f"Send {tools.money(value)} to {p.name}" + (f" · {note}" if note else ""),
        {"to": p.slug, "memo": note},
        amount=value,
    )
    return {
        "action_id": action.id,
        "to": p.name,
        "amount": tools.money(value),
        "safe_for_you": effect.get("verdict") == "safe",
        "your_lowest_after": effect.get("lowest_balance_with_it"),
        **_waiting(f"{tools.money(value)} goes from your checking to {p.name}."),
    }


def _people(persona: str) -> list[Any]:
    from app import safety_views

    return safety_views.people_for(persona).people


def request_from_person(
    person: str = "", amount: float = 0, memo: str = "", *, persona: str = engine.DEFAULT_PERSONA, today=None
) -> dict[str, Any]:
    """Propose asking someone in the user's circles for money. Nothing moves until they pay it."""
    value = _money_arg(amount)
    p = _connected_person(persona, person)
    if p is None:
        return {"not_connected": person, "people_you_can_ask": [x.name for x in _people(persona)]}
    note = memo.strip()[:80]
    action = _propose(
        persona,
        "person_request",
        f"Ask {p.name} for {tools.money(value)}" + (f" · {note}" if note else ""),
        {"to": p.slug, "memo": note},
        amount=value,
    )
    return {
        "action_id": action.id,
        "ask": p.name,
        "amount": tools.money(value),
        **_waiting(f"{p.name} gets a request; nothing moves until they pay it from their own account."),
    }


def pay_back(
    person: str = "", amount: float | None = None, *, persona: str = engine.DEFAULT_PERSONA, today=None
) -> dict[str, Any]:
    """Propose paying back support the user received from `person`: all of it, or `amount` of it."""
    from app import safety_views

    who = person.strip().lower()
    out = [b for b in safety_views.summary(persona).borrowed if b.status in ("active", "repay_failed")]
    b = next((x for x in out if who in (x.lender_name.lower(), x.lender)), None)
    if b is None:
        return {
            "nothing_out_from": person,
            "you_owe": [{"to": x.lender_name, "amount": tools.money(x.amount)} for x in out],
        }
    value = b.amount if amount in (None, 0) else _money_arg(amount)
    if not 1 <= value <= b.amount:
        return {"owed_to": b.lender_name, "out_now": tools.money(b.amount), "error": "Pick from $1 up to what's out."}
    # the repayment's own rule (safety_net.repay_now): checking stays at or above what they keep, today
    mine, _ = tools._inputs(persona, today or sources.local_today())
    room = max(0.0, mine.checking - mine.safe_floor)
    if room < value:  # it would be refused at approval, so no card: say what would work instead
        return {
            "to": b.lender_name,
            "asked_to_pay": tools.money(value),
            "out_now": tools.money(b.amount),
            "goes_through_now": False,
            "most_you_can_pay_now": tools.money(min(b.amount, math.floor(room))),
            "goes_back_on": f"payday, {tools.day(b.due_date)}",
            "rule": f"Paying back can't take your checking under the {tools.money(mine.safe_floor)} you keep.",
        }
    part = value < b.amount
    action = _propose(
        persona,
        "repay",
        f"Pay {b.lender_name} back {tools.money(value)}" + (f" of {tools.money(b.amount)}" if part else ""),
        {"bridge_id": b.id, "lender": b.lender},
        amount=value,
    )
    return {
        "action_id": action.id,
        "to": b.lender_name,
        "paying": tools.money(value),
        "out_now": tools.money(b.amount),
        "still_out_after": tools.money(b.amount - value),
        "goes_through_now": room >= value,
        "most_you_can_pay_now": tools.money(min(b.amount, math.floor(room))),
        "rule": "It only goes through if your checking stays at or above the amount you keep, "
        f"{tools.money(mine.safe_floor)}. Whatever's still out goes back on payday as usual.",
        **_waiting(
            f"{tools.money(value)} goes back to {b.lender_name}"
            + (f"; {tools.money(b.amount - value)} stays out until payday." if part else ".")
        ),
    }


def resume_support(person: str = "", *, persona: str = engine.DEFAULT_PERSONA, today=None) -> dict[str, Any]:
    """Propose turning the user's paused support for `person` back on."""
    summary, a = tools._my_agreement(persona, person)
    if a is None:
        return {"supports_them": False, "people_you_support": [x.recipient_name for x in summary.supporting]}
    if a.state == "active":
        return {"supports_them": True, "person": a.recipient_name, "already": "on"}
    action = _propose(
        persona, "resume_support", f"Turn your support for {a.recipient_name} back on", {"recipient": a.recipient}
    )
    return {
        "action_id": action.id,
        "person": a.recipient_name,
        "your_limit_for_them": tools.money(a.limit or 0),
        **_waiting(f"Runway can cover {a.recipient_name} again, within your limit and your own cushion."),
    }


# ---------- circles ----------


def create_circle(
    name: str = "", invite: list[str] | None = None, *, persona: str = engine.DEFAULT_PERSONA, today=None
) -> dict[str, Any]:
    """Propose creating a named circle with the user in it, and inviting `invite` in the same approval."""
    name = name.strip()
    if not 1 <= len(name) <= 40:
        return {"error": "Give the circle a name of up to 40 characters."}
    found = {n: _runway_person(persona, n) for n in (invite or [])[:10]}
    people = [p for p in found.values() if p is not None and p[0] != persona]
    missing = [n for n, p in found.items() if p is None]
    names = " and ".join(first for _, first in people)
    action = _propose(
        persona,
        "circle_create",
        f'Create the circle "{name}"' + (f" and invite {names}" if names else ""),
        {"name": name, "invite": [slug for slug, _ in people]},
    )
    return {
        "action_id": action.id,
        "circle": name,
        "inviting": [first for _, first in people],
        **({"not_on_runway": missing, "tip": "Share an invite link with them instead."} if missing else {}),
        **_waiting("The circle is created with you in it" + (f", and {names} invited." if names else ".")),
    }


def invite_to_circle(circle: str = "", person: str = "", *, persona: str = engine.DEFAULT_PERSONA, today=None):
    """Propose inviting someone on Runway into one of the user's circles."""
    c, p = _circle(persona, circle), _runway_person(persona, person)
    if c is None:
        return {"no_circle": circle, "your_circles": _circle_names(persona)}
    if p is None:
        return {"no_person": person, "note": "They need to be on Runway; share an invite link instead."}
    slug, first = p
    action = _propose(persona, "circle_invite", f"Invite {first} to {c.name}", {"circle": c.id, "slug": slug})
    return {
        "action_id": action.id,
        "circle": c.name,
        "invite": first,
        **_waiting(f"{first} is invited; joining a circle shares no money and no balances."),
    }


def remove_from_circle(circle: str = "", person: str = "", *, persona: str = engine.DEFAULT_PERSONA, today=None):
    """Propose removing someone from a circle (only the person who made it can)."""
    c = _circle(persona, circle)
    if c is None:
        return {"no_circle": circle, "your_circles": _circle_names(persona)}
    who = person.strip().lower()
    m = next((x for x in c.members if who in (x.name.lower(), x.slug) and x.slug != persona), None)
    if m is None:
        return {"not_in_circle": person, "members": [x.name for x in c.members if x.slug != persona]}
    action = _propose(persona, "circle_remove", f"Remove {m.name} from {c.name}", {"circle": c.id, "slug": m.slug})
    return {"action_id": action.id, "circle": c.name, "remove": m.name, **_waiting(f"{m.name} leaves {c.name}.")}


def leave_circle(circle: str = "", *, persona: str = engine.DEFAULT_PERSONA, today=None) -> dict[str, Any]:
    """Propose leaving one of the user's circles."""
    c = _circle(persona, circle)
    if c is None:
        return {"no_circle": circle, "your_circles": _circle_names(persona)}
    action = _propose(persona, "circle_leave", f"Leave {c.name}", {"circle": c.id})
    return {"action_id": action.id, "circle": c.name, **_waiting(f"You leave {c.name}.")}


def answer_circle_invite(
    circle: str = "", accept: bool = True, *, persona: str = engine.DEFAULT_PERSONA, today=None
) -> dict[str, Any]:
    """Propose accepting or declining an invitation to a circle."""
    c = _circle(persona, circle)
    if c is None or c.my_state != "invited":
        invites = [x.name for x in _circles_invited(persona)]
        return {"no_invitation_to": circle, "your_invitations": invites}
    kind, verb = ("circle_accept", "Join") if accept else ("circle_decline", "Decline the invitation to")
    action = _propose(persona, kind, f"{verb} {c.name}", {"circle": c.id})
    return {"action_id": action.id, "circle": c.name, **_waiting(f"{verb} {c.name}.")}


def _circles_invited(persona: str) -> list[Any]:
    from app import safety_views

    return [c for c in safety_views.circles_for(persona) if c.my_state == "invited"]


def share_circle_link(circle: str = "", *, persona: str = engine.DEFAULT_PERSONA, today=None) -> dict[str, Any]:
    """Propose making a 7-day invite link for one of the user's circles; the link appears once approved."""
    c = _circle(persona, circle)
    if c is None:
        return {"no_circle": circle, "your_circles": _circle_names(persona)}
    action = _propose(persona, "circle_link", f"Make an invite link for {c.name}", {"circle": c.id})
    return {"action_id": action.id, "circle": c.name, **_waiting("A link anyone can use to join, for 7 days.")}


READ_TOOLS = {"my_circles": my_circles}
WRITE_TOOLS = {
    "send_money": send_money,
    "request_from_person": request_from_person,
    "pay_back": pay_back,
    "resume_support": resume_support,
    "create_circle": create_circle,
    "invite_to_circle": invite_to_circle,
    "remove_from_circle": remove_from_circle,
    "leave_circle": leave_circle,
    "answer_circle_invite": answer_circle_invite,
    "share_circle_link": share_circle_link,
}


def _decl(name: str, description: str, props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    params: dict[str, Any] = {"type": "object", "properties": props}
    if required:
        params["required"] = required
    return {"type": "function", "name": name, "description": description, "parameters": params}


_PERSON = {"type": "string", "description": "First name, as the user said it."}
_CIRCLE = {"type": "string", "description": "The circle's name, as the user said it."}
_AMOUNT = {"type": "number", "description": "Dollars, exactly as the user said them."}
_MEMO = {"type": "string", "description": "Optional short note, e.g. 'pizza'."}
_PROPOSES = " Only proposes it: the user approves before anything happens."

DECLARATIONS: list[dict[str, Any]] = [
    _decl(
        "my_circles",
        "The user's circles, who's in each, their invitations, and who they can send to or ask for money. "
        "Use for 'what circles am I in', 'who's in Family', or before a circle action if unsure of a name.",
        {},
    ),
    _decl(
        "send_money",
        "Send money from the user's checking to someone in their circles (any time, for anything)." + _PROPOSES,
        {"person": _PERSON, "amount": _AMOUNT, "memo": _MEMO},
        ["person", "amount"],
    ),
    _decl(
        "request_from_person",
        "Ask someone in the user's circles for money. For splitting a bill with a contact, use request_money."
        + _PROPOSES,
        {"person": _PERSON, "amount": _AMOUNT, "memo": _MEMO},
        ["person", "amount"],
    ),
    _decl(
        "pay_back",
        "Pay back safety-net support the user received: all of it, or part (e.g. '$60 of the $100')." + _PROPOSES,
        {
            "person": {**_PERSON, "description": "First name of who covered them."},
            "amount": {
                **_AMOUNT,
                "description": "Dollars to pay back now; leave out to pay back everything that's out.",
            },
        },
        ["person"],
    ),
    _decl(
        "resume_support",
        "Turn the user's paused support for someone back on." + _PROPOSES,
        {"person": _PERSON},
        ["person"],
    ),
    _decl(
        "create_circle",
        "Create a named circle (e.g. 'Roommates'), optionally inviting people in the same step." + _PROPOSES,
        {
            "name": _CIRCLE,
            "invite": {"type": "array", "items": {"type": "string"}, "description": "First names to invite."},
        },
        ["name"],
    ),
    _decl(
        "invite_to_circle",
        "Invite someone on Runway into one of the user's circles." + _PROPOSES,
        {"circle": _CIRCLE, "person": _PERSON},
        ["circle", "person"],
    ),
    _decl(
        "remove_from_circle",
        "Remove someone from a circle the user made." + _PROPOSES,
        {"circle": _CIRCLE, "person": _PERSON},
        ["circle", "person"],
    ),
    _decl("leave_circle", "Leave one of the user's circles." + _PROPOSES, {"circle": _CIRCLE}, ["circle"]),
    _decl(
        "answer_circle_invite",
        "Accept or decline an invitation to a circle." + _PROPOSES,
        {"circle": _CIRCLE, "accept": {"type": "boolean", "description": "true to join, false to decline."}},
        ["circle", "accept"],
    ),
    _decl(
        "share_circle_link",
        "Make a 7-day invite link for one of the user's circles, to share with anyone." + _PROPOSES,
        {"circle": _CIRCLE},
        ["circle"],
    ),
]

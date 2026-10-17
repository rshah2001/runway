"""Network Guardian — how much each supporter can SAFELY give, and how a need is split between them.

Pure and deterministic: no I/O, no LLM. The safety net (app/safety_net.py) feeds it forecasts from the
one forecast engine and acts on what it returns.

A supporter's safe capacity is the largest transfer that keeps every constraint true for the WHOLE
time the money is out (today → the recipient's expected repayment, plus grace days):

    cash room      = lowest *cautious* (p5) balance in that window − the supporter's own cushion
    pair room      = their limit for this person − what this person already owes them
    exposure room  = their total cap across everyone − everything currently owed to them

    capacity = round down to $5 of max(0, min(cash room, pair room, exposure room))

Using the cautious band rather than today's balance is the point: Sam may hold $2,400 today, but if a
large bill lands before Maya can repay, his safe capacity is what's left after that bill on a bad week.
Money that is expected but hasn't arrived only helps after the day it lands, because the window's
minimum is taken over every day. When the forecast isn't confident yet, nothing is automatic.
"""

import math
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

ALGORITHM_VERSION = "guardian-1.2"  # stored on every decision, so an old decision can be explained later
STEP = Decimal(5)  # capacities and needs are whole fives: $91.60 short → $95
DEFAULT_EXPOSURE = Decimal(500)  # a supporter's total cap across everyone, unless they set their own

Bound = Literal["cushion", "pair_limit", "exposure", "low_confidence", "no_forecast", "approval_only"]


@dataclass(frozen=True)
class Capacity:
    amount: Decimal  # safe to move automatically
    bound: Bound  # which constraint set the amount (shown to the supporter, never to anyone else)
    cash_room: Decimal  # what the cushion alone allows — an over-limit APPROVAL may use up to this


def round_up(x: Decimal) -> Decimal:
    return Decimal(math.ceil(x / STEP)) * STEP


def round_down(x: Decimal) -> Decimal:
    return Decimal(math.floor(max(Decimal(0), x) / STEP)) * STEP


def capacity(
    cautious_days: list[tuple[date, Decimal]],
    cushion: Decimal,
    *,
    start: date,
    end: date,
    pair_remaining: Decimal,
    exposure_remaining: Decimal,
    confident: bool,
) -> Capacity:
    """A supporter's safe capacity over [start, end] (both inclusive). See the module docstring."""
    window = [bal for d, bal in cautious_days if start <= d <= end]
    if not window:
        return Capacity(Decimal(0), "no_forecast", Decimal(0))
    cash = round_down(min(window) - cushion)
    rooms = {"cushion": cash, "pair_limit": round_down(pair_remaining), "exposure": round_down(exposure_remaining)}
    bound = min(rooms, key=lambda k: (rooms[k], list(rooms).index(k)))  # ties: cushion first, it's the real limit
    if not confident:
        return Capacity(Decimal(0), "low_confidence", min(cash, rooms["exposure"]))
    return Capacity(rooms[bound], bound, min(cash, rooms["exposure"]))


def allocate(need: Decimal, caps: list[tuple[str, Capacity]]) -> list[tuple[str, Decimal]]:
    """Split `need` across supporters' automatic capacities: the fewest people first (largest capacity
    first; ties by name, so the same inputs always give the same answer). Returns only positive shares;
    the shares add up to `need` when there is enough capacity, otherwise to as much as is safe."""
    shares, left = [], need
    for slug, cap in sorted(caps, key=lambda sc: (-sc[1].amount, sc[0])):
        if left <= 0:
            break
        give = min(cap.amount, left)
        if give > 0:
            shares.append((slug, give))
            left -= give
    return shares


# ---------- several people short at once ----------
@dataclass(frozen=True)
class NetNeed:
    """One recipient's need in a network pass, with the supporters who could help them automatically."""

    borrower: str
    need: Decimal
    shortfall: date
    options: tuple[tuple[str, Decimal, Decimal], ...]  # (supporter, their shared room, pair room for this person)
    allow_multi: bool = True


def allocate_network(needs: list[NetNeed]) -> dict[str, list[tuple[str, Decimal]]]:
    """Cover several needs at once from supporters whose safe room is SHARED between them.

    Fairness rule (written down, deterministic, never about who "deserves" it): serve the person with the
    fewest options first — the least spare capacity beyond their need — then the earliest shortfall, then
    name order. Each supporter's room (their cushion- and exposure-bound amount) is used up across
    everyone; each pair limit applies per person. First-come-first-served would let whoever is planned
    first take a supporter someone else has no alternative to; fewest-options-first covers more need
    (see tests/test_guardian.py::test_network_*). A need may be covered only in part: the rest is unmet.
    """
    room: dict[str, Decimal] = {}
    for n in needs:  # a supporter's shared room is the smallest any recipient's window allows
        for s, r, _ in n.options:
            room[s] = min(room.get(s, r), r)

    def slack(n: NetNeed) -> Decimal:
        return sum((min(room[s], pair) for s, _, pair in n.options), Decimal(0)) - n.need

    out: dict[str, list[tuple[str, Decimal]]] = {}
    for n in sorted(needs, key=lambda n: (slack(n), n.shortfall, n.borrower)):
        caps = [(s, Capacity(round_down(min(room[s], pair)), "pair_limit", room[s])) for s, _, pair in n.options]
        if not n.allow_multi:
            caps = [(s, c) for s, c in caps if c.amount >= n.need]
        shares = allocate(n.need, caps)
        for s, a in shares:
            room[s] -= a
        out[n.borrower] = shares
    return out

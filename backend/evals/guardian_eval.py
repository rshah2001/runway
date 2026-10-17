"""Network Guardian eval: does every decision keep every promise — and how much need does it cover?

Two parts, both deterministic (fixed seed; no model involved anywhere):

1. **The demo, on the real engine** — the seeded personas, every demo day: Maya's need, each
   supporter's safe share, who was protected.
2. **2,000 generated networks** — 1–4 supporters with random forecasts (some dipping inside the lending
   window), cushions, limits, money already out, exposure caps and forecast confidence, and a random
   need. Every decision is checked against the invariants the safety net promises:

     pair limit     no share is more than the supporter's limit minus what's already out to this person
     exposure       no share is more than the supporter's total cap minus everything they've committed
     cushion        every share keeps the supporter's cautious balance ≥ their cushion for the whole window
     no overshoot   shares never add up to more than the need
     confidence     nothing is automatic for a supporter whose forecast isn't confident
     deterministic  the same inputs always give the same decision

   and the report counts what the Guardian achieved: need covered vs unmet, how many authorized-but-
   unsafe transfers it blocked (a limit allowed it, the supporter's own forecast didn't), and how often a
   need was split across supporters.

Run:  python -m evals.guardian_eval        (from backend/)
"""

import os
import random
import sys
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal as D

os.environ.setdefault("RUNWAY_FORCE_MOCK", "1")  # the seeded data, never live balances

from app import guardian  # noqa: E402
from app.cashflow import Projection  # noqa: E402
from app.safety_net import REPAY_GRACE_DAYS, Helper, decide  # noqa: E402

TODAY = date(2026, 10, 18)
PAYDAY = date(2026, 10, 23)
SCENARIOS = 2000
SEED = 1018


def _projection(
    slug: str, rng: random.Random, *, base: float, dip: float | None, dip_day: int, floor: float, confident: bool
):
    days = [(TODAY + timedelta(days=n), D(str(round(base, 2)))) for n in range(35)]
    if dip is not None:
        days[dip_day] = (days[dip_day][0], D(str(round(dip, 2))))
    low = [(d, b - D(str(round(rng.uniform(0, 200), 2)))) for d, b in days]  # the cautious band sits below
    return Projection(
        slug, slug.title(), 40, days[0][1], days, None, None, floor=D(str(floor)), days_low=low, confident=confident
    )


def _borrower(need: float) -> Projection:
    """A recipient whose expected low before payday is `need` under a $300 cushion, fine afterwards."""
    days = []
    for n in range(35):
        d = TODAY + timedelta(days=n)
        bal = 300 - need if d == PAYDAY - timedelta(days=1) else (2000 if d >= PAYDAY else 900)
        days.append((d, D(str(round(bal, 2)))))
    return Projection("maya", "Maya", 20, days[0][1], days, PAYDAY, D(780))


def _network(rng: random.Random) -> tuple[Projection, list[Helper]]:
    need = rng.choice([25, 60, 95, 135, 180, 240, 400])
    helpers = []
    for i in range(rng.randint(1, 4)):
        floor = rng.choice([0, 300, 500, 1500])
        base = rng.uniform(200, 6000)
        dips = rng.random() < 0.45
        helpers.append(
            Helper(
                projection=_projection(
                    f"s{i}",
                    rng,
                    base=base,
                    dip=rng.uniform(-500, base) if dips else None,
                    dip_day=rng.randint(1, 12),
                    floor=floor,
                    confident=rng.random() < 0.85,
                ),
                limit=D(str(rng.choice([25, 45, 100, 150, 300, 500]))),
                outstanding=D(str(rng.choice([0, 0, 0, 20, 60]))),
                enabled=True,
                is_borrowing=False,
                exposure_remaining=D(str(rng.choice([500, 500, 200, 60, 0]))),
            )
        )
    return _borrower(need), helpers


def check(b: Projection, helpers: list[Helper]) -> tuple[list[str], dict]:
    """(violations, stats) for one decision."""
    d = decide(b, helpers, TODAY)
    again = decide(b, helpers, TODAY)
    by = {h.projection.slug: h for h in helpers}
    end = b.next_payday + timedelta(days=REPAY_GRACE_DAYS)
    bad = []
    if (d.action, d.allocations) != (again.action, again.allocations):
        bad.append("deterministic")
    auto = d.action == "auto_bridge"
    total = sum((a for _, a in d.allocations), D(0))
    if auto and total > d.amount:
        bad.append("no overshoot")
    blocked = 0
    for h in helpers:
        cap = guardian.capacity(
            h.projection.days_low,
            h.projection.floor,
            start=TODAY,
            end=end,
            pair_remaining=h.remaining,
            exposure_remaining=h.exposure_remaining,
            confident=h.projection.confident,
        )
        if (
            h.remaining > 0
            and h.exposure_remaining > 0
            and cap.amount == 0
            and cap.bound in ("cushion", "low_confidence")
        ):
            blocked += 1  # a limit authorized it; the supporter's own forecast didn't
    for slug, amount in d.allocations if auto else ():
        h = by[slug]
        if amount > h.remaining:
            bad.append("pair limit")
        if amount > h.exposure_remaining:
            bad.append("exposure")
        if not h.projection.confident:
            bad.append("confidence")
        window = [bal for day, bal in h.projection.days_low if TODAY <= day <= end]
        if min(window) - amount < h.projection.floor:
            bad.append("cushion")
    stats = {
        "need": d.amount if d.action in ("auto_bridge", "needs_approval", "no_safe_helper") else D(0),
        "covered": total if auto else D(0),
        "split": auto and len(d.allocations) > 1,
        "blocked": blocked,
        "action": d.action,
    }
    return bad, stats


def demo_on_the_engine() -> list[str]:
    from app import prefs
    from app.cashflow import projection_for
    from seed.personas import PERSONAS, SAFETY_LIMITS

    ages = {p.slug: p.age for p in PERSONAS}
    lines = []
    for offset in range(5):
        today = TODAY + timedelta(days=offset)

        def project(slug: str, today: date = today) -> Projection:
            p = projection_for(slug, first_name=slug.title(), age=ages[slug], today=today)
            return replace(p, floor=D(str(prefs.default_floor(slug))))

        helpers = [
            Helper(project(s), D(str(lim)), D(0), True, False, guardian.DEFAULT_EXPOSURE)
            for s, r, lim in SAFETY_LIMITS
            if r == "maya"
        ]
        d = decide(project("maya"), helpers, today)
        shares = ", ".join(f"{s} ${a}" for s, a in d.allocations)
        held = ", ".join(f"{s} ({why})" for s, _, why in d.held) or "nobody"
        lines.append(f"| {today:%b %d} | ${d.amount} | {shares} | {held} |")
    return lines


def run(scenarios: int = SCENARIOS) -> int:
    print("Demo on the real engine (Maya's need → safe shares; protected supporters)\n")
    print("| Day | Need | Shares | Protected |\n|---|---|---|---|")
    print("\n".join(demo_on_the_engine()))

    rng = random.Random(SEED)
    violations: dict[str, int] = {}
    need = covered = D(0)
    splits = blocked = autos = 0
    actions: dict[str, int] = {}
    for _ in range(scenarios):
        bad, st = check(*_network(rng))
        for v in bad:
            violations[v] = violations.get(v, 0) + 1
        need += st["need"]
        covered += st["covered"]
        splits += st["split"]
        blocked += st["blocked"]
        autos += st["action"] == "auto_bridge"
        actions[st["action"]] = actions.get(st["action"], 0) + 1

    print(f"\n{scenarios:,} generated networks (seed {SEED})\n")
    print("| Invariant | Violations |\n|---|---|")
    for name in ("pair limit", "exposure", "cushion", "no overshoot", "confidence", "deterministic"):
        print(f"| {name} | {violations.get(name, 0)} |")
    print("\n| Outcome | Value |\n|---|---|")
    print(f"| decisions moving money automatically | {autos:,} |")
    print(f"| need identified | ${need:,.0f} |")
    print(f"| covered automatically | ${covered:,.0f} ({covered / need * 100 if need else 0:.0f}%) |")
    print(f"| left to an approval or uncovered | ${need - covered:,.0f} |")
    print(f"| authorized-but-unsafe transfers blocked | {blocked:,} |")
    print(f"| needs split across supporters | {splits:,} |")
    print(f"| actions | {', '.join(f'{k} {v}' for k, v in sorted(actions.items()))} |")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(run())

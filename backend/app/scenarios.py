"""Time Machine: the signed-in person's own forecast under four what-ifs, for the Today chart.

  A  no help              — your forecast as if nobody covered you
  B  one supporter        — the single biggest safe share alone
  C  coordinated support  — what the Network Guardian actually arranges (or arranged)
  D  unsafe help blocked  — the whole need covered anyway, ignoring supporters' safety: what Runway
                            refuses to do. Only shown when the safe split (C) falls short.

Each scenario adds the help today and takes it back on payday, exactly as the safety net would, so the
curves are honest. Privacy: everything here is the viewer's OWN forecast plus amounts they can already
see (who covered them, and supporters' limits). D never says which supporter was held back or why — that
would be their finances.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.cashflow import Projection
from app.schemas import Scenario, ScenarioPoint, Scenarios


@dataclass(frozen=True)
class Inputs:
    base: Projection  # the viewer's forecast WITHOUT any help
    shares: list[tuple[str, Decimal]]  # (supporter's first name, amount): what the Guardian arranges / arranged
    authorized: Decimal  # the sum of every active supporter's remaining limit for the viewer
    need: Decimal  # how much the viewer is short before payday (0 if fine)


def _with_help(base: Projection, amount: Decimal) -> list[tuple[date, Decimal]]:
    """Help arrives today and goes back on payday."""
    payday = base.next_payday
    return [(d, b + amount if payday is None or d < payday else b) for d, b in base.days]


def _scenario(key: str, label: str, inputs: Inputs, help_: Decimal, note: str, *, blocked: bool = False) -> Scenario:
    days = _with_help(inputs.base, help_)
    end = inputs.base.next_payday
    window = [(d, b) for d, b in days if end is None or d < end] or days
    low_day, low = min(window, key=lambda x: x[1])
    return Scenario(
        key=key,
        label=label,
        help=float(help_),
        low=ScenarioPoint(date=low_day, balance=float(low)),
        covered=low >= inputs.base.floor,
        blocked=blocked,
        note=note,
        points=[ScenarioPoint(date=d, balance=float(b)) for d, b in days],
    )


def build(inputs: Inputs) -> Scenarios:
    """The four what-ifs (D only when it differs from C). Pure — no I/O."""
    shares = inputs.shares
    coordinated = sum((a for _, a in shares), Decimal(0))
    biggest = max(shares, key=lambda s: s[1]) if shares else None
    out = [_scenario("A", "No help", inputs, Decimal(0), "Your forecast if nobody covered you.")]
    if biggest:
        out.append(_scenario("B", f"Only {biggest[0]}", inputs, biggest[1], f"{biggest[0]}'s safe share on its own."))
    if len(shares) > 1 or not biggest:
        who = " + ".join(f"{n} ${a:,.0f}" for n, a in shares) or "nobody can help safely right now"
        out.append(_scenario("C", "Your circle", inputs, coordinated, f"What Runway arranges: {who}."))
    if coordinated < inputs.need and inputs.authorized > coordinated:  # the safe split falls short
        out.append(
            _scenario(
                "D",
                "Unsafe help",
                inputs,
                min(inputs.need, inputs.authorized),
                "Covering all of it would put someone who agreed to help at risk with their own bills. "
                "Runway won't do that.",
                blocked=True,
            )
        )
    return Scenarios(
        floor=float(inputs.base.floor),
        payday=inputs.base.next_payday,
        need=float(inputs.need),
        scenarios=out,
    )


OUT = ("funding", "active", "repaying", "repay_failed", "reconcile")


def _without(p: Projection, amount: Decimal) -> Projection:
    """The forecast as if help already received hadn't come (it arrived before payday, goes back on it)."""
    payday = p.next_payday
    days = [(d, b - amount if payday is None or d < payday else b) for d, b in p.days]
    return Projection(
        p.slug,
        p.first_name,
        p.age,
        p.start_balance - amount,
        days,
        p.next_payday,
        p.paycheck,
        p.events,
        p.floor,
        p.days_low,
        p.confident,
    )


def inputs_for(slug: str) -> Inputs:
    """The viewer's own scenario inputs, live or demo."""
    from app import safety_views
    from app.config import get_settings

    support = safety_views.support_for(slug)
    authorized = sum((Decimal(str(a.limit or 0)) for a in support.supporters if a.state == "active"), Decimal(0))
    if not get_settings().live:
        return _demo_inputs(slug, authorized)
    from app import safety_net
    from app.cashflow import project
    from app.db import pool, repo

    with pool.connection() as conn:
        p = project(conn, slug)
        summary = safety_views.summary(slug)
        open_help = [b for b in summary.borrowed if b.status in OUT]
        if open_help:  # already covered: compare against life without that help
            got = sum((Decimal(str(b.amount)) for b in open_help), Decimal(0))
            return Inputs(
                _without(p, got), [(b.lender_name, Decimal(str(b.amount))) for b in open_help], authorized, got
            )
        d = safety_net.plan(conn, slug)
        names = {r["slug"]: r["first_name"] for r in repo.personas(conn)}
    shares = [(names.get(s, s.title()), a) for s, a in d.allocations] if d.action == "auto_bridge" else []
    need = d.amount if d.action in ("auto_bridge", "needs_approval", "no_safe_helper") else Decimal(0)
    return Inputs(p, shares, authorized, need)


def _demo_inputs(slug: str, authorized: Decimal) -> Inputs:
    """Offline: the seeded personas on the real engine, with the scripted agreements."""
    from dataclasses import replace

    from app import guardian, prefs
    from app.cashflow import projection_for
    from app.forecast import sources
    from app.safety_net import Helper, decide
    from seed.personas import DEMO_PAUSED, DEMO_WAITING_FOR_RECIPIENT, PERSONAS, SAFETY_LIMITS

    today = sources.local_today()
    names = {p.slug: p.first_name for p in PERSONAS}
    ages = {p.slug: p.age for p in PERSONAS}

    def project(s: str) -> Projection:
        p = projection_for(s, first_name=names[s], age=ages[s], today=today)
        return replace(p, floor=Decimal(str(prefs.default_floor(s))))

    active = [
        (s, lim)
        for s, r, lim in SAFETY_LIMITS
        if r == slug and (s, r) not in DEMO_PAUSED and (s, r) not in DEMO_WAITING_FOR_RECIPIENT
    ]
    helpers = [
        Helper(project(s), Decimal(str(lim)), Decimal(0), True, False, guardian.DEFAULT_EXPOSURE) for s, lim in active
    ]
    base = project(slug)
    d = decide(base, helpers, today)
    shares = [(names[s], a) for s, a in d.allocations] if d.action == "auto_bridge" else []
    need = d.amount if d.action in ("auto_bridge", "needs_approval", "no_safe_helper") else Decimal(0)
    return Inputs(base, shares, authorized, need)

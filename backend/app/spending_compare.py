"""Month-over-month spending, compared fairly.

A month in progress is compared with the SAME days of the previous month (Oct 1–17 vs Sep 1–17): set
against a whole previous month, any partial month would look like "spending less" just because it isn't
over. A finished month is compared whole. Pure — no I/O; the route feeds it two `Spending` results.
"""

from app.schemas import CategoryChange, Spending, SpendingCompare


def _upto(s: Spending, through_day: int | None) -> dict[str, float]:
    totals: dict[str, float] = {}
    for t in s.transactions:
        if through_day is None or t.date.day <= through_day:
            totals[t.category] = totals.get(t.category, 0.0) + t.amount
    return totals


def compare(this: Spending, last: Spending, *, through_day: int | None) -> SpendingCompare:
    """`this` month against `last`, through `through_day` of each (None = whole months)."""
    now, then = _upto(this, through_day), _upto(last, through_day)
    cats = [
        CategoryChange(
            category=c,
            this=round(now.get(c, 0.0), 2),
            last=round(then.get(c, 0.0), 2),
            change=round(now.get(c, 0.0) - then.get(c, 0.0), 2),
        )
        for c in set(now) | set(then)
    ]
    this_total, last_total = round(sum(now.values()), 2), round(sum(then.values()), 2)
    return SpendingCompare(
        previous_month=last.month,
        through_day=through_day,
        this_total=this_total,
        last_total=last_total,
        change=round(this_total - last_total, 2),
        categories=sorted(cats, key=lambda c: (-abs(c.change), c.category)),  # biggest change first
    )

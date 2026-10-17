"""Month-over-month spending, compared fairly: the same days of each month, never a partial month
against a whole one."""

from datetime import date

from app.schemas import Spending, SpendingTransaction
from app.spending_compare import compare


def tx(d: str, category: str, amount: float) -> SpendingTransaction:
    return SpendingTransaction(
        date=date.fromisoformat(d), merchant="m", category=category, amount=amount, account="credit"
    )


def month(m: str, txs: list[SpendingTransaction]) -> Spending:
    return Spending(month=m, total=sum(t.amount for t in txs), categories=[], daily=[], transactions=txs)


def test_a_month_in_progress_is_compared_with_the_same_days_last_month() -> None:
    oct_ = month("2026-10", [tx("2026-10-03", "Dining", 40), tx("2026-10-10", "Groceries", 100)])
    sep = month(
        "2026-09", [tx("2026-09-05", "Dining", 70), tx("2026-09-12", "Groceries", 90), tx("2026-09-25", "Dining", 500)]
    )
    c = compare(oct_, sep, through_day=17)
    assert c.through_day == 17 and c.previous_month == "2026-09"
    assert c.this_total == 140 and c.last_total == 160 and c.change == -20  # Sep 25 is past the 17th: left out
    by = {x.category: x for x in c.categories}
    assert by["Dining"].change == -30 and by["Groceries"].change == 10


def test_a_finished_month_is_compared_whole() -> None:
    sep = month("2026-09", [tx("2026-09-25", "Dining", 50)])
    aug = month("2026-08", [tx("2026-08-30", "Dining", 20)])
    c = compare(sep, aug, through_day=None)
    assert c.through_day is None and c.change == 30


def test_categories_are_ordered_by_the_biggest_change_and_include_ones_that_stopped() -> None:
    oct_ = month("2026-10", [tx("2026-10-02", "Dining", 10)])
    sep = month("2026-09", [tx("2026-09-02", "Dining", 15), tx("2026-09-03", "Entertainment", 60)])
    c = compare(oct_, sep, through_day=17)
    assert [x.category for x in c.categories] == ["Entertainment", "Dining"]
    assert c.categories[0].this == 0 and c.categories[0].change == -60

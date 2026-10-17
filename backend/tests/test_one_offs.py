"""One-offs: a big unusual purchase is flagged and kept out of the everyday spending rate."""

from dataclasses import replace
from datetime import date

import pytest

from app.forecast import schedule, sources

TODAY = date(2026, 10, 16)
REPAIR = sources.Txn(date(2026, 9, 20), "purchase", -406.0, "Midas Auto Repair", "Auto", "Checking")


def _maya(*extra: sources.Txn) -> sources.PersonaData:
    data = sources.load("maya", TODAY)
    return replace(data, history=sorted([*data.history, *extra], key=lambda t: t.date))


def test_a_car_repair_is_left_out_of_the_rate_and_listed() -> None:
    plain, with_repair = schedule.build(_maya(), TODAY), schedule.build(_maya(REPAIR), TODAY)
    assert with_repair.spend.expected(TODAY) == pytest.approx(plain.spend.expected(TODAY))
    r = with_repair.readiness
    assert r is not None and [(o.label, o.amount) for o in r.left_out] == [("Midas Auto Repair", 406.0)]
    assert "Left out of your usual spending: $406.00 Midas Auto Repair on Sep 20." in r.reasons


def test_a_one_off_still_widens_the_range() -> None:
    plain, with_repair = schedule.build(_maya(), TODAY), schedule.build(_maya(REPAIR), TODAY)
    assert sum(with_repair.daily_spend) == pytest.approx(sum(plain.daily_spend) + 406.0)


def test_big_but_regular_is_a_habit_not_a_one_off() -> None:
    runs = [replace(REPAIR, date=date(2026, m, 3), label="Costco") for m in (8, 9, 10)]
    r = schedule.build(_maya(*runs), TODAY).readiness
    assert r is not None and r.left_out == []


def test_rare_but_small_is_not_a_one_off() -> None:
    cafe = replace(REPAIR, amount=-30.0, label="New Cafe")
    r = schedule.build(_maya(cafe), TODAY).readiness
    assert r is not None and r.left_out == []


@pytest.mark.parametrize("persona", ["maya", "jordan", "sam"])
def test_seeded_everyday_spending_has_no_false_alarms(persona: str) -> None:
    r = schedule.build(sources.load(persona, TODAY), TODAY).readiness
    assert r is not None and r.left_out == []

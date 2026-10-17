"""Network Guardian on the demo's own numbers: Maya short $135; Sam authorized $150 but can safely give
$90; Jordan authorized $300 but a big bill makes it $0; Emma can give $45."""

from datetime import date, timedelta
from decimal import Decimal as D

from app.guardian import Capacity, allocate, capacity

TODAY = date(2026, 10, 17)
END = date(2026, 10, 26)  # Maya's payday + grace


def flat(low_on_day: dict[int, float], base: float = 2000) -> list[tuple[date, D]]:
    return [(TODAY + timedelta(days=n), D(str(low_on_day.get(n, base)))) for n in range(35)]


def cap(days, pair=1000, exposure=500, confident=True):
    return capacity(
        days, D(300), start=TODAY, end=END, pair_remaining=D(pair), exposure_remaining=D(exposure), confident=confident
    )


def test_capacity_is_bound_by_the_cushion_on_the_cautious_band_not_todays_balance() -> None:
    sam = flat({5: 390})  # $2,000 most days, $390 on a bad week after a big bill
    c = cap(sam, pair=150)
    assert c.amount == D(90) and c.bound == "cushion"


def test_a_big_obligation_inside_the_window_blocks_an_authorized_supporter() -> None:
    jordan = flat({6: 159})
    assert cap(jordan, pair=300).amount == D(0)


def test_a_dip_after_the_money_is_back_does_not_count() -> None:
    assert cap(flat({20: 0}), pair=100).amount == D(100)  # day 20 is after the window


def test_money_already_out_reduces_room() -> None:
    assert cap(flat({}), pair=100 - 60).amount == D(40)
    c = cap(flat({}), pair=1000, exposure=500 - 450)
    assert c.amount == D(50) and c.bound == "exposure"


def test_low_confidence_means_nothing_automatic() -> None:
    c = cap(flat({}), pair=150, confident=False)
    assert c.amount == D(0) and c.bound == "low_confidence" and c.cash_room > 0


def test_allocate_135_as_sam_90_and_emma_45() -> None:
    caps = [
        ("sam", Capacity(D(90), "cushion", D(90))),
        ("jordan", Capacity(D(0), "cushion", D(0))),
        ("emma", Capacity(D(200), "pair_limit", D(800))),
    ]
    assert allocate(D(135), caps) == [("emma", D(135))]  # one person can cover it: fewest transfers
    caps[2] = ("emma", Capacity(D(45), "pair_limit", D(800)))
    assert allocate(D(135), caps) == [("sam", D(90)), ("emma", D(45))]


def test_allocation_is_partial_when_capacity_runs_out_and_never_overcommits() -> None:
    assert allocate(D(135), [("sam", Capacity(D(90), "cushion", D(90)))]) == [("sam", D(90))]


def test_allocation_is_deterministic_on_ties() -> None:
    caps = [("sam", Capacity(D(50), "cushion", D(50))), ("emma", Capacity(D(50), "cushion", D(50)))]
    assert allocate(D(60), caps) == [("emma", D(50)), ("sam", D(10))]


# ---------- several people short at once ----------
from app.guardian import NetNeed, allocate_network  # noqa: E402

DAY = date(2026, 10, 22)


def maya_and_alex(alex_first_by_name: bool = True) -> list[NetNeed]:
    """Sam's safe room this week is $90, shared. Maya needs $135 (Sam ≤ $150, Emma ≤ $45); Alex needs $85
    (Sam ≤ $100, Emma ≤ $50). Maya has no alternative to Sam; Alex does."""
    return [
        NetNeed("alex", D(85), DAY, (("sam", D(90), D(100)), ("emma", D(3000), D(50)))),
        NetNeed("maya", D(135), DAY, (("sam", D(90), D(150)), ("emma", D(3000), D(45)))),
    ]


def test_network_serves_the_person_with_fewest_options_first() -> None:
    split = allocate_network(maya_and_alex())
    assert split["maya"] == [("sam", D(90)), ("emma", D(45))]  # fully covered
    assert split["alex"] == [("emma", D(50))]  # $35 stays uncovered — honestly partial


def test_network_covers_more_than_first_come_first_served() -> None:
    fewest_first = sum(a for shares in allocate_network(maya_and_alex()).values() for _, a in shares)
    # first-come (Alex planned first by name): Sam alone covers Alex, leaving Maya only Sam's $5 + Emma's $45
    first_come = D(85) + D(5) + D(45)
    assert fewest_first == D(185) and fewest_first > first_come


def test_network_never_spends_a_supporters_room_twice() -> None:
    split = allocate_network(maya_and_alex())
    sam_total = sum(a for shares in split.values() for s, a in shares if s == "sam")
    assert sam_total <= D(90)
    for n in maya_and_alex():
        for s, a in split[n.borrower]:
            assert a <= dict((x, pair) for x, _, pair in n.options)[s]  # pair limits per person


def test_network_is_deterministic() -> None:
    assert allocate_network(maya_and_alex()) == allocate_network(list(reversed(maya_and_alex())))

"""Every safety-net guardrail, tested on the pure decide() — no database, no Nessie."""

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal as D

from app.cashflow import Projection
from app.safety_net import Helper, decide

TODAY = date(2026, 10, 17)
PAYDAY = date(2026, 11, 6)


def proj(
    slug: str, low: float, *, payday: date | None = PAYDAY, after_payday: float = 900, days: int = 35
) -> Projection:
    """A projection that sits at 1,000, dips to `low` on Nov 5, and recovers after payday."""
    out = []
    for n in range(days):
        d = TODAY + timedelta(days=n)
        bal = D(1000)
        if d == date(2026, 11, 5):
            bal = D(str(low))
        elif payday and d >= payday:
            bal = D(str(after_payday))
        out.append((d, bal))
    return Projection(slug, slug.title(), 20, D(1000), out, payday, D(780))


def helper(slug: str, low: float, limit: float, outstanding: float = 0, enabled: bool = True, borrowing: bool = False):
    """A family member whose balance sits flat at `low` (their lowest point) all month."""
    flat = [(TODAY + timedelta(days=n), D(str(low))) for n in range(35)]
    return Helper(
        Projection(slug, slug.title(), 60, D(str(low)), flat, None, None),
        D(str(limit)),
        D(str(outstanding)),
        enabled,
        borrowing,
    )


def test_no_dip_means_no_bridge() -> None:
    assert decide(proj("maya", 450), [helper("sam", 5000, 100)], TODAY).action == "none"


def test_dip_under_the_limit_is_covered_automatically_and_due_on_payday() -> None:
    d = decide(proj("maya", 208.40), [helper("sam", 5000, 100)], TODAY)
    assert d.action == "auto_bridge" and d.lender == "sam"
    assert d.amount == D(95)  # $91.60 gap rounded up to whole fives
    assert d.shortfall_date == date(2026, 11, 5) and d.due_date == PAYDAY


def test_over_the_limit_asks_the_lender() -> None:
    d = decide(proj("maya", 150), [helper("sam", 5000, 100)], TODAY)
    assert d.action == "needs_approval" and d.amount == D(150) and d.lender == "sam"


def test_money_already_out_counts_against_the_limit() -> None:
    d = decide(proj("maya", 208), [helper("sam", 5000, limit=100, outstanding=60)], TODAY)
    assert d.action == "needs_approval"  # only $40 of the $100 limit is left


def test_helping_must_be_safe_for_the_helper() -> None:
    d = decide(proj("maya", 208), [helper("jordan", 350, 500)], TODAY)  # 350 - 100 < 300 floor
    assert d.action == "no_safe_helper"


def test_one_supporter_with_the_most_safe_room_covers_it_alone() -> None:
    d = decide(proj("maya", 208), [helper("jordan", 2000, 200), helper("sam", 9000, 300)], TODAY)
    assert d.allocations == (("sam", D(95)),)
    assert d.lender == "sam"


def test_prefers_someone_whose_limit_covers_it_over_asking() -> None:
    d = decide(proj("maya", 208), [helper("sam", 9000, 50), helper("jordan", 2000, 200)], TODAY)
    assert d.action == "auto_bridge" and d.lender == "jordan"


def test_disabled_limits_and_people_who_owe_money_never_lend() -> None:
    helpers = [helper("sam", 9000, 500, enabled=False), helper("jordan", 9000, 500, borrowing=True)]
    assert decide(proj("maya", 208), helpers, TODAY).action == "no_safe_helper"


def test_no_payday_means_it_could_not_come_back() -> None:
    assert decide(proj("maya", 208, payday=None), [helper("sam", 9000, 500)], TODAY).action == "no_payday"
    far = TODAY + timedelta(days=40)
    assert decide(proj("maya", 208, payday=far), [helper("sam", 9000, 500)], TODAY).action == "no_payday"


def test_one_bridge_at_a_time() -> None:
    d = decide(proj("maya", 208), [helper("sam", 9000, 500)], TODAY, has_open_bridge=True)
    assert d.action == "already_covered"


def test_never_bridges_if_repaying_on_payday_would_break_the_borrower() -> None:
    d = decide(proj("maya", 208, after_payday=250), [helper("sam", 9000, 500)], TODAY)
    assert d.action == "no_safe_helper" and "repaying" in d.reason


def test_huge_gaps_are_not_bridged() -> None:
    assert decide(proj("maya", -2000), [helper("sam", 90000, 5000)], TODAY).action == "no_safe_helper"


def test_two_supporters_split_a_need_neither_can_cover_alone() -> None:
    maya = proj("maya", 165)  # $135 short of $300
    sam, emma = helper("sam", 390, 150), helper("emma", 2000, 45)  # Sam: $90 above his cushion
    d = decide(maya, [sam, emma, helper("jordan", 159, 300)], TODAY)
    assert d.action == "auto_bridge" and d.amount == D(135)
    assert d.allocations == (("sam", D(90)), ("emma", D(45)))


def test_a_supporter_whose_forecast_is_unsure_is_only_ever_asked() -> None:
    sam = helper("sam", 9000, 500)
    unsure = replace(sam, projection=replace(sam.projection, confident=False))
    d = decide(proj("maya", 208), [unsure], TODAY)
    assert d.action == "needs_approval" and d.lender == "sam"


def test_approval_only_supporters_are_asked_never_auto_moved() -> None:
    sam = helper("sam", 9000, 500)
    d = decide(proj("maya", 208), [replace(sam, automatic=False)], TODAY)
    assert d.action == "needs_approval" and d.lender == "sam" and not d.held


def test_the_recipients_own_cap_on_what_they_owe_at_once() -> None:
    d = decide(proj("maya", 165), [helper("sam", 9000, 500)], TODAY, owe_room=D(100))
    assert d.action == "no_safe_helper" and "owe at once" in d.reason  # $135 is more than her $100 cap


def test_one_supporter_only_when_the_recipient_says_so() -> None:
    helpers = [helper("sam", 390, 150), helper("emma", 2000, 45)]  # $90 + $45 would split it
    d = decide(proj("maya", 165), helpers, TODAY, allow_multi=False)
    assert d.action != "auto_bridge" and len(d.allocations) <= 1

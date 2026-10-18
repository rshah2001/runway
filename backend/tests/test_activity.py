"""Activity: every entry explained from the viewer's own side — and a supporter's never carries the
recipient's balance, reason or other supporters."""

from datetime import date
from decimal import Decimal as D

from fastapi.testclient import TestClient

from app import activity, main
from tests.test_privacy_alerts import auth_off  # noqa: F401 (fixture, used by name)

client = TestClient(main.app)
BRIDGE = {
    "id": "bridge-1",
    "borrower_slug": "maya",
    "borrower_name": "Maya",
    "lender_slug": "sam",
    "lender_name": "Sam",
    "amount": D(90),
    "status": "active",
    "due_date": date(2026, 10, 23),
    "created_at": date(2026, 10, 18),
    "funded_at": date(2026, 10, 18),
    "repaid_at": None,
    "reason": "Maya would drop to $165 on Oct 22 … Sam covers $90 and Emma covers $45",
    "out_transfer_id": "t-sam",
    "out_deposit_id": "d-maya",
}


def test_the_supporter_sees_their_own_limit_and_cushion_never_her_reason() -> None:
    i = activity.item(BRIDGE, "sam", my_limit=150, my_floor=300)
    assert i.kind == "provided" and "$150 limit" in i.why and "$300 you keep" in i.why
    assert "165" not in i.why and "Emma" not in i.why and "Oct 22" not in i.why
    assert i.reference == "t-sam"  # his own side of the transfer


def test_the_recipient_sees_who_covered_her_and_when_it_goes_back() -> None:
    i = activity.item(BRIDGE, "maya", my_limit=None, my_floor=300)
    assert i.kind == "received" and i.title == "Sam covered you" and i.reference == "d-maya"
    assert "verified payday" in i.why


def test_an_unclear_transfer_says_so_plainly() -> None:
    i = activity.item({**BRIDGE, "status": "reconcile"}, "sam", my_limit=150, my_floor=300)
    assert "confirming" in i.why and "twice" in i.why


def test_activity_route_returns_only_my_side() -> None:
    import pytest

    pytest.importorskip("fastapi")
    body = client.get("/activity?persona=sam").json()
    assert body and all("165" not in x["why"] for x in body)


def test_paid_back_help_stays_in_the_timeline_as_two_entries() -> None:
    repaid = {**BRIDGE, "status": "repaid", "repaid_at": date(2026, 10, 23), "back_transfer_id": "t-back"}
    items = activity.feed("maya", [repaid], {}, 300)
    assert [i.kind for i in items] == ["repaid_by_me", "received"]  # newest first
    assert items[1].title == "Sam covered you" and items[1].status == "Paid back"


def test_sends_and_requests_between_people_are_in_the_timeline() -> None:
    from datetime import datetime

    pay = {
        "id": "ppay-1",
        "from_slug": "sam",
        "from_name": "Sam",
        "to_slug": "maya",
        "to_name": "Maya",
        "amount": D(50),
        "memo": "🎉 Festival",
        "ts": datetime(2026, 10, 18, 12),
        "transfer_id": "t1",
        "deposit_id": "d1",
    }
    ask = {
        "id": "preq-1",
        "from_slug": "maya",
        "from_name": "Maya",
        "to_slug": "jordan",
        "to_name": "Jordan",
        "amount": D(20),
        "memo": "🍕 Food",
        "status": "open",
        "created_at": datetime(2026, 10, 18, 13),
    }
    items = {i.kind: i for i in activity.feed("maya", [], {}, 300, [pay], [ask])}
    assert items["got"].title == "Sam sent you $50" and items["got"].reference == "d1"
    assert items["asked"].title == "You asked Jordan for $20" and items["asked"].status.startswith("Waiting")

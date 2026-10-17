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

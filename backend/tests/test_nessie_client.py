"""NessieClient against a fake Nessie (httpx.MockTransport) — no network, no keys."""

from datetime import date
from decimal import Decimal

import httpx
import pytest

from app.nessie.client import NessieClient, NessieError, from_cents, to_cents


def make_client(handler, retries: int = 2) -> NessieClient:
    client = NessieClient("test-key", "https://nessie.test", retries=retries, transport=httpx.MockTransport(handler))
    return client


def test_create_unwraps_object_created_and_always_sends_status(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["body"] = str(request.url), request.read()
        return httpx.Response(201, json={"code": 201, "objectCreated": {"_id": "p1", "amount": 12.5}})

    out = make_client(handler).create_purchase("acc1", "m1", 12.499, date(2026, 8, 1), "groceries")
    assert out == {"_id": "p1", "amount": 12.5}
    assert seen["url"].startswith("https://nessie.test/accounts/acc1/purchases?key=test-key")
    body = httpx.Response(200, content=seen["body"]).json()
    assert body["status"] == "completed" and body["purchase_date"] == "2026-08-01"
    assert body["amount"] == 1250  # integer cents: Nessie truncates decimal dollars


def test_transfer_has_no_payee_field() -> None:
    bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(httpx.Response(200, content=request.read()).json())
        return httpx.Response(201, json={"objectCreated": {"_id": "t1"}})

    make_client(handler).create_transfer("sav", 100, date(2026, 10, 17), "Fix it")
    assert set(bodies[0]) == {"transaction_date", "status", "amount", "description"}


def test_empty_list_404_becomes_empty_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json="No transfers found for this account")

    assert make_client(handler).transfers("acc1") == []


def test_retries_transient_errors_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.nessie.client.time.sleep", lambda _: None)
    calls = iter([httpx.Response(503), httpx.Response(429), httpx.Response(200, json=[{"_id": "c1"}])])
    assert make_client(lambda r: next(calls)).customers() == [{"_id": "c1"}]


def test_client_errors_raise_with_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.nessie.client.time.sleep", lambda _: None)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json="status field required")

    with pytest.raises(NessieError) as err:
        make_client(handler).create_deposit("acc1", 10, date(2026, 8, 1), "pay")
    assert err.value.status == 400


@pytest.mark.parametrize("dollars", [0, 0.01, 5.5, 15.49, 286.40, 1150, 6500.99])
def test_cents_round_trip_is_exact(dollars: float) -> None:
    cents = to_cents(dollars)
    assert isinstance(cents, int)
    assert from_cents(cents) == Decimal(str(dollars)).quantize(Decimal("0.01"))


def test_writes_are_not_retried_on_server_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 5xx on a POST may already have been applied — retrying could create a second transfer."""
    monkeypatch.setattr("app.nessie.client.time.sleep", lambda _: None)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        return httpx.Response(503)

    with pytest.raises(NessieError):
        make_client(handler).create_transfer("sav", 100, date(2026, 10, 17), "Fix it")
    assert calls == ["POST"]


def test_writes_are_retried_when_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    """429 means Nessie refused before processing, so a retry cannot double-apply."""
    monkeypatch.setattr("app.nessie.client.time.sleep", lambda _: None)
    calls = iter([httpx.Response(429), httpx.Response(201, json={"objectCreated": {"_id": "t1"}})])
    assert make_client(lambda r: next(calls)).create_transfer("sav", 100, date(2026, 10, 17), "Fix it") == {"_id": "t1"}

"""Send and request between connected people: only people in your circles or agreements, only the person
asked pays, and a request never carries anything but the amount and the note."""

import json
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient

from app import main, people_pay
from tests.test_privacy_alerts import auth_off  # noqa: F401 (fixture, used by name)

client = TestClient(main.app)


def test_you_can_only_ask_people_you_are_connected_to(monkeypatch) -> None:
    monkeypatch.setattr(people_pay, "people", lambda conn, me: [{"slug": "sam", "name": "Sam", "how": "Family"}])
    assert people_pay.connected(None, "maya", "sam")
    assert not people_pay.connected(None, "maya", "jordan") and not people_pay.connected(None, "maya", "maya")
    with pytest.raises(people_pay.NotConnected):
        people_pay.new_request(None, "maya", "jordan", D(40), "Festival 🎉")


@pytest.mark.usefixtures("auth_off")
def test_my_people_come_from_my_circles_and_agreements_and_carry_no_money() -> None:
    body = client.get("/people?persona=maya").json()
    names = {p["name"]: p["how"] for p in body["people"]}
    assert {"Sam", "Jordan", "Emma", "Alex"} <= set(names)
    assert "Family" in names["Sam"]
    text = json.dumps(body).lower()
    assert "balance" not in text and "limit" not in text


@pytest.mark.usefixtures("auth_off")
def test_sending_needs_real_transfers_and_requests_answer_only_known_ids() -> None:
    body = {"persona": "maya", "to": "sam", "amount": 50, "memo": "Festival 🎉", "client_key": "tap-12345678"}
    assert client.post("/people/send", json=body).status_code == 503  # offline: nothing can move
    assert client.post("/people/requests/not-a-request/pay", json={"persona": "sam"}).status_code == 404
    assert client.post("/people/request", json=body).status_code == 200

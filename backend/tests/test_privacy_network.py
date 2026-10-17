"""The privacy boundary of the safety network, on the real routes with real (locally signed) tokens:
being someone's supporter never opens their money, and nobody can act on anyone else's side."""

import json

import pytest
from fastapi.testclient import TestClient

from app import main
from tests.test_auth_routes import as_, auth_on  # noqa: F401 (fixture, used by name)

client = TestClient(main.app)
pytestmark = pytest.mark.usefixtures("auth_on")
MAYA_PRIVATE = ("balance", "projected_low", "paycheck", "spending", "shortfall")


def _text(r) -> str:
    assert r.status_code == 200, r.text
    return json.dumps(r.json()).lower()


def test_asking_for_someone_elses_data_returns_your_own() -> None:
    for path in ("/me", "/forecast", "/support", "/safety-net", "/spending", "/p2p"):
        body = client.get(f"{path}?persona=maya", headers=as_("sam")).json()
        assert body.get("persona", body.get("first_name", "sam")).lower() in ("sam", ""), path


def test_a_supporters_view_of_the_network_carries_none_of_the_recipients_money() -> None:
    support = _text(client.get("/support", headers=as_("sam")))
    assert not any(word in support for word in MAYA_PRIVATE)
    lent = client.get("/safety-net", headers=as_("sam")).json()["lent"]
    assert all(b["reason"].startswith("Covering") for b in lent)  # never the stored reason with her balance


def test_nobody_can_say_yes_for_someone_else() -> None:
    r = client.post("/support/consent", json={"supporter": "emma", "recipient": "maya"}, headers=as_("sam"))
    assert r.status_code == 403


def test_nobody_outside_an_agreement_can_stop_it() -> None:
    r = client.post("/support/revoke", json={"supporter": "sam", "recipient": "maya"}, headers=as_("jordan"))
    assert r.status_code == 403


def test_a_recipient_cannot_set_a_supporters_limit() -> None:
    body = {"lender": "sam", "borrower": "maya", "limit": 1000}
    assert client.put("/safety-net/limits", json=body, headers=as_("maya")).status_code == 403

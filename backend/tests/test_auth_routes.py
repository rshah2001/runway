"""Sign-in on the real routes: browsing stays open, money needs the owner. Local keys, no network."""

import pytest
from fastapi.testclient import TestClient

from app import data, main
from app.auth import deps, tokens
from app.auth.tokens import PERSONA_CLAIM
from tests.test_auth import CFG, _tenant_key, _token

client = TestClient(main.app)


@pytest.fixture
def auth_on(monkeypatch: pytest.MonkeyPatch) -> None:
    real = tokens.user_from_header
    monkeypatch.setattr(deps, "config", lambda: CFG)
    monkeypatch.setattr(main, "auth_config", lambda: CFG)
    monkeypatch.setattr(deps, "user_from_header", lambda h, cfg: real(h, cfg, _tenant_key))


@pytest.fixture
def real_money(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pretend LIVE_TRANSFERS=1 — the authorization gate is what's under test, not Nessie."""
    monkeypatch.setattr(data, "writes_enabled", lambda: True)


def as_(persona: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(sub=f'auth0|{persona}', **{PERSONA_CLAIM: persona})}"}


def test_browsing_without_an_account_keeps_the_demo_switcher(auth_on: None) -> None:
    assert client.get("/me?persona=jordan").json()["first_name"] == "Jordan"


def test_signed_in_you_only_ever_see_your_own_data(auth_on: None) -> None:
    assert client.get("/me?persona=maya", headers=as_("sam")).json()["first_name"] == "Sam"
    assert client.get("/safety-net?persona=maya", headers=as_("sam")).json()["persona"] == "sam"


def test_a_bad_token_is_rejected_even_on_reads(auth_on: None) -> None:
    assert client.get("/me", headers={"Authorization": "Bearer not-a-jwt"}).status_code == 401


def test_only_the_lender_sets_their_limit(auth_on: None) -> None:
    body = {"lender": "sam", "borrower": "maya", "limit": 150}
    assert client.put("/safety-net/limits", json=body, headers=as_("maya")).status_code == 403
    assert client.put("/safety-net/limits", json=body, headers=as_("sam")).status_code == 200


def test_only_the_lender_answers_a_bridge(auth_on: None) -> None:
    bridge = client.get("/safety-net?persona=jordan").json()["approvals_waiting"][0]  # Jordan is the lender
    assert client.post(f"/safety-net/bridges/{bridge['id']}/approve", headers=as_("maya")).status_code == 403
    assert client.post(f"/safety-net/bridges/{bridge['id']}/approve", headers=as_("jordan")).status_code == 200


def test_a_fix_it_can_only_be_approved_by_whoever_it_was_proposed_for(auth_on: None) -> None:
    from app.agent import tools
    from app.schemas import PendingAction

    action = PendingAction(id="auth-test-sam", kind="transfer", description="Move $50", amount=50)
    tools.PENDING[action.id], tools.ACTION_PERSONA[action.id] = action, "sam"
    assert client.post(f"/actions/{action.id}/approve", headers=as_("maya")).status_code == 403
    assert action.status == "awaiting_approval"  # the refused attempt claimed nothing
    assert client.post(f"/actions/{action.id}/approve", headers=as_("sam")).status_code == 200


def test_you_cannot_send_money_as_someone_else(auth_on: None) -> None:
    body = {"persona": "sam", "contact_id": "sam-emma", "amount": 20, "memo": "x"}
    assert client.post("/p2p/send", json=body, headers=as_("maya")).status_code == 403


def test_real_money_needs_a_signed_in_owner(auth_on: None, real_money: None) -> None:
    body = {"persona": "maya", "contact_id": "maya-alex", "amount": 20, "memo": "x"}
    assert client.post("/p2p/send", json=body).status_code == 401  # anonymous
    assert client.put("/safety-net/limits", json={"lender": "sam", "borrower": "maya", "limit": 50}).status_code == 401
    assert client.post("/safety-net/run").status_code == 401


def test_real_money_is_refused_when_sign_in_is_not_configured(real_money: None, monkeypatch) -> None:
    monkeypatch.setattr(main, "auth_config", lambda: None)
    body = {"persona": "maya", "contact_id": "maya-alex", "amount": 20, "memo": "x"}
    assert client.post("/p2p/send", json=body).status_code == 503


def test_with_real_money_off_the_simulation_stays_open(auth_on: None) -> None:
    body = {"persona": "maya", "contact_id": "maya-alex", "amount": 20, "memo": "x"}
    assert client.post("/p2p/send", json=body).status_code == 200

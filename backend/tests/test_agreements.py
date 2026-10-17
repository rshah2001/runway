"""Quiet Support Agreements: a limit is a number, consent takes both people, and a legacy limit is
never mistaken for anyone's yes."""

from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient

from app import agreements, main, safety_net
from tests.test_privacy_alerts import auth_off  # noqa: F401 (fixture, used by name)
from tests.test_safety_net import TODAY, helper, proj

client = TestClient(main.app)


def row(supporter=None, recipient=None, revoked=None, limit=D(100), enabled=True, version=1):
    return {
        "supporter": "sam",
        "recipient": "maya",
        "supporter_consent_at": supporter,
        "recipient_consent_at": recipient,
        "revoked_at": revoked,
        "limit_amount": limit,
        "enabled": enabled,
        "version": version,
    }


def test_a_migrated_legacy_limit_is_not_consent() -> None:
    assert agreements.state(row()) == "needs_both" and not agreements.is_active(row())


def test_both_yeses_make_it_active_and_one_is_not_enough() -> None:
    assert agreements.state(row("t", "t")) == "active"
    assert agreements.state(row("t", None)) == "needs_recipient"
    assert agreements.state(row(None, "t")) == "needs_supporter"


def test_a_paused_limit_or_a_revocation_stops_automatic_help() -> None:
    assert agreements.state(row("t", "t", enabled=False)) == "paused"
    assert agreements.state(row(revoked="t")) == "revoked"


def test_only_the_two_people_can_act_on_an_agreement() -> None:
    with pytest.raises(agreements.NotYourAgreement):
        agreements.side_of("jordan", "sam", "maya")
    assert agreements.side_of("maya", "sam", "maya") == "recipient"


@pytest.mark.parametrize("consent", [(None, None), ("t", None), (None, "t"), ("t", "t")])
def test_plan_only_ever_asks_supporters_with_an_active_agreement(monkeypatch: pytest.MonkeyPatch, consent) -> None:
    sam = helper("sam", 5000, 100)
    monkeypatch.setattr(safety_net.repo, "personas", lambda c: [{"slug": "maya"}, {"slug": "sam"}])
    monkeypatch.setattr(safety_net, "project", lambda c, s, t: proj("maya", 208) if s == "maya" else sam.projection)
    monkeypatch.setattr(safety_net.prefs, "setting", lambda *a, **k: True)
    monkeypatch.setattr(safety_net.safety_repo, "open_bridges", lambda c: [])
    monkeypatch.setattr(safety_net.safety_repo, "open_bridge_for_borrower", lambda c, s: None)
    monkeypatch.setattr(
        safety_net.safety_repo,
        "limits",
        lambda c, borrower: [{"lender_slug": "sam", "limit_amount": 100, "outstanding": 0, "enabled": True}],
    )
    monkeypatch.setattr(safety_net.agreements_repo, "involving", lambda c, s: [row(*consent, version=7)])
    monkeypatch.setattr(safety_net, "_exposure_limit", lambda c, s: D(500))
    d = safety_net.plan(None, "maya", TODAY)
    if consent == ("t", "t"):
        assert d.action == "auto_bridge" and d.lender == "sam" and d.versions == (("sam", 7),)
    else:
        assert d.action == "no_safe_helper" and d.lender is None


def test_money_promised_but_not_yet_sent_cannot_be_offered_twice(monkeypatch: pytest.MonkeyPatch) -> None:
    consent = ("t", "t")
    sam = helper("sam", 5000, 100)
    monkeypatch.setattr(safety_net.repo, "personas", lambda c: [{"slug": "maya"}, {"slug": "sam"}])
    monkeypatch.setattr(safety_net, "project", lambda c, s, t: proj("maya", 208) if s == "maya" else sam.projection)
    monkeypatch.setattr(safety_net.prefs, "setting", lambda *a, **k: True)
    waiting = {"lender_slug": "sam", "borrower_slug": "jordan", "amount": D(4800), "status": "pending_approval"}
    monkeypatch.setattr(safety_net.safety_repo, "open_bridges", lambda c: [waiting])
    monkeypatch.setattr(safety_net.safety_repo, "open_bridge_for_borrower", lambda c, s: None)
    monkeypatch.setattr(
        safety_net.safety_repo,
        "limits",
        lambda c, borrower: [{"lender_slug": "sam", "limit_amount": 100, "outstanding": 0, "enabled": True}],
    )
    monkeypatch.setattr(safety_net.agreements_repo, "involving", lambda c, s: [row(*consent, version=7)])
    monkeypatch.setattr(safety_net, "_exposure_limit", lambda c, s: D(500))
    monkeypatch.setattr(safety_net, "_exposure_limit", lambda c, s: D(9000))
    d = safety_net.plan(None, "maya", TODAY)
    assert d.action == "no_safe_helper"  # $5,000 − $4,800 promised to Jordan leaves Sam under his cushion


@pytest.mark.usefixtures("auth_off")
def test_nobody_can_consent_for_someone_else() -> None:
    r = client.post("/support/consent", json={"persona": "jordan", "supporter": "sam", "recipient": "maya"})
    assert r.status_code == 403


@pytest.mark.usefixtures("auth_off")
def test_support_view_never_carries_balances() -> None:
    body = client.get("/support?persona=maya").json()
    assert body["supporters"] and all(a["my_side"] == "recipient" for a in body["supporters"])
    text = str(body).lower()
    assert "balance" not in text and "paycheck" not in text and "spend" not in text

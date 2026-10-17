"""Alerts-only and family privacy: the two answers to why people in the buyer panel said no
("I avoid looking at my balance" and "I'd be embarrassed having family see my money")."""

import pytest
from fastapi.testclient import TestClient

from app import main, prefs, safety_net, safety_views
from tests.test_auth_routes import as_, auth_on  # noqa: F401 (fixtures)
from tests.test_safety_net import TODAY, proj

client = TestClient(main.app)
PEOPLE = ["maya", "jordan", "sam"]


@pytest.fixture(autouse=True)
def fresh() -> None:
    prefs.reset(PEOPLE)
    yield
    prefs.reset(PEOPLE)


@pytest.fixture
def auth_off(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.auth import deps

    monkeypatch.setattr(deps, "config", lambda: None)
    monkeypatch.setattr(main, "auth_config", lambda: None)


# ---------- the settings ----------
def test_defaults_are_the_full_screen_with_family_cover_on(auth_off: None) -> None:
    me = client.get("/me?persona=maya").json()
    assert me["alerts_only"] is False and me["family_cover"] is True


def test_turning_alerts_only_on_changes_only_that_setting(auth_off: None) -> None:
    r = client.put("/me/preferences", json={"persona": "maya", "alerts_only": True})
    assert r.status_code == 200
    assert r.json()["alerts_only"] is True and r.json()["family_cover"] is True  # left out = unchanged
    assert client.get("/me?persona=jordan").json()["alerts_only"] is False  # nobody else changes


def test_signed_out_you_cant_change_them(auth_on: None) -> None:  # noqa: F811
    assert client.put("/me/preferences", json={"persona": "maya", "family_cover": False}).status_code == 401
    assert prefs.setting("maya", "family_cover") is True


def test_signed_in_you_only_ever_change_your_own(auth_on: None) -> None:  # noqa: F811
    r = client.put("/me/preferences", json={"persona": "maya", "family_cover": False}, headers=as_("sam"))
    assert r.status_code == 200 and r.json()["first_name"] == "Sam"
    assert prefs.setting("sam", "family_cover") is False and prefs.setting("maya", "family_cover") is True


def test_unknown_people_are_refused(auth_off: None) -> None:
    assert client.put("/me/preferences", json={"persona": "nobody", "alerts_only": True}).status_code == 404


def test_reset_puts_the_settings_back() -> None:
    prefs.set_setting("maya", "alerts_only", True)
    prefs.reset(["maya"])
    assert prefs.setting("maya", "alerts_only") is False


# ---------- family cover off: no relative's money moves to you, whatever limit they set ----------
def test_family_cover_off_means_nobody_is_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(safety_net.repo, "personas", lambda conn: [{"slug": "maya"}, {"slug": "sam"}])
    monkeypatch.setattr(safety_net, "project", lambda conn, slug, today: proj(slug, 208))
    prefs.set_setting("maya", "family_cover", False)
    d = safety_net.plan(None, "maya", TODAY)
    assert d.action == "family_off" and d.lender is None and d.amount == 0


# ---------- what the person covering you can see ----------
def test_the_helper_never_sees_the_borrowers_balance() -> None:
    sam = safety_views.demo_summary("sam")  # Sam covers Maya
    maya = safety_views.demo_summary("maya")
    assert "$208" in maya.borrowed[0].reason  # Maya sees her own numbers
    for b in sam.lent:
        assert "$" not in b.reason and b.reason == f"Covering {b.borrower_name} until payday."
    for b in safety_views.demo_summary("jordan").approvals_waiting:
        assert "$" not in b.reason


def test_answering_a_bridge_returns_the_helpers_view(auth_off: None) -> None:
    r = client.post("/safety-net/bridges/demo-b2/approve")
    assert r.status_code == 200 and "$" not in r.json()["reason"]

"""Alerts-only and family privacy: the two answers to why people in the buyer panel said no
("I avoid looking at my balance" and "I'd be embarrassed having family see my money")."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app import alerts, main, prefs, safety_net, safety_views
from app.schemas import ForecastPoint
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


# ---------- review fixes ----------
class _Row:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class _Conn:
    def __init__(self, row):
        self.row = row

    def execute(self, *_a, **_k):
        return _Row(self.row)


def test_a_settings_only_row_reads_as_no_floor_set() -> None:
    from app.db import repo

    assert repo.safe_floor(_Conn({"safe_floor": None}), "maya") is None  # → the default, never a crash


# ---------- heads-up alerts ----------


def _points(*balances: float) -> list[ForecastPoint]:
    return [ForecastPoint(date=TODAY + timedelta(days=i), balance=b) for i, b in enumerate(balances)]


def test_the_alert_names_the_first_dip_within_a_few_days() -> None:
    assert alerts.first_dip(_points(900, 800, 250, 100), 300, TODAY) == TODAY + timedelta(days=2)
    far = _points(*([900] * (alerts.ALERT_AHEAD_DAYS + 1)), 100)
    assert alerts.first_dip(far, 300, TODAY) is None  # too far ahead to be sure: no alert yet
    assert alerts.first_dip(_points(900, 800), 300, TODAY) is None


def test_the_lock_screen_text_has_no_amounts() -> None:
    m = alerts.message(TODAY + timedelta(days=2), TODAY)
    assert "$" not in m["title"] + m["body"] and "Nothing moves until you say yes" in m["body"]


@pytest.fixture
def push_on(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict]]:
    sent: list[tuple[str, dict]] = []
    monkeypatch.setenv("VAPID_PUBLIC_KEY", "pub-key-for-tests")
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "priv-key-for-tests")
    monkeypatch.setattr(alerts, "send", lambda sub, payload, keys: sent.append((sub["slug"], payload)) or True)
    alerts._demo_subs.clear()
    alerts.reset(PEOPLE)
    yield sent
    alerts._demo_subs.clear()
    alerts.reset(PEOPLE)


def test_one_alert_per_dip_however_often_the_pass_runs(push_on, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.forecast import engine
    from app.schemas import Forecast

    pts = _points(900, 250, 600)
    f = Forecast(points=pts, low=pts[1], safe_floor=300, events=[])
    monkeypatch.setattr(engine, "forecast", lambda days, persona: f)
    alerts.subscribe("maya", "https://fcm.googleapis.com/fcm/send/maya", "p" * 20, "a" * 20)
    assert alerts.run(TODAY) == 1 and alerts.run(TODAY) == 0  # the second pass stays quiet
    assert len(push_on) == 1 and push_on[0][0] == "maya"


def test_without_keys_alerts_are_simply_off(auth_off: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VAPID_PUBLIC_KEY", raising=False)
    assert client.get("/alerts/key").json()["key"] is None
    body = {"persona": "maya", "endpoint": "https://fcm.googleapis.com/x", "p256dh": "p" * 20, "auth": "a" * 20}
    assert client.put("/me/push", json=body).status_code == 503
    assert alerts.run(TODAY) == 0


def test_a_browser_subscribes_for_yourself_only(push_on, auth_on: None) -> None:  # noqa: F811
    body = {"persona": "maya", "endpoint": "https://web.push.apple.com/s", "p256dh": "p" * 20, "auth": "a" * 20}
    assert client.put("/me/push", json=body).status_code == 401
    assert client.put("/me/push", json=body, headers=as_("sam")).status_code == 200
    assert [s["slug"] for s in alerts.subscriptions()] == ["sam"]


def test_only_https_push_services_are_accepted(push_on, auth_off: None) -> None:
    body = {"persona": "maya", "endpoint": "http://169.254.169.254/latest", "p256dh": "p" * 20, "auth": "a" * 20}
    assert client.put("/me/push", json=body).status_code == 422


def test_only_real_push_services_are_accepted() -> None:
    assert alerts.allowed_endpoint("https://fcm.googleapis.com/fcm/send/abc")
    assert alerts.allowed_endpoint("https://web.push.apple.com/QAbc")
    assert alerts.allowed_endpoint("https://wns2-by3p.notify.windows.com/w/?token=x")
    assert not alerts.allowed_endpoint("https://evil.example/fcm.googleapis.com")
    assert not alerts.allowed_endpoint("https://fcm.googleapis.com.evil.example/x")
    assert not alerts.allowed_endpoint("https://fcm.googleapis.com:8443/x")
    assert not alerts.allowed_endpoint("https://notify.windows.com.evil.example/x")

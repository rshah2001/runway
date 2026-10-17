"""Everyone keeps their own amount in checking: the forecast, the agent and the safety net all
measure against it, and only the person themselves can change it."""

from dataclasses import replace
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient

from app import main, prefs
from app.safety_net import decide
from tests.test_auth_routes import as_, auth_on  # noqa: F401 (fixtures)
from tests.test_safety_net import TODAY, helper, proj

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def fresh() -> None:
    prefs.reset(["maya", "jordan", "sam"])
    yield
    prefs.reset(["maya", "jordan", "sam"])


# ---------- the safety net ----------
def test_a_lower_cushion_means_the_same_balance_is_no_dip() -> None:
    maya = proj("maya", 208)
    assert decide(maya, [helper("sam", 5000, 100)], TODAY).action == "auto_bridge"  # under $300
    calm = replace(maya, floor=D(100))  # she's fine down to $100
    assert decide(calm, [helper("sam", 5000, 100)], TODAY).action == "none"


def test_a_higher_cushion_asks_for_more() -> None:
    careful = replace(proj("maya", 208), floor=D(500))
    d = decide(careful, [helper("sam", 5000, 400)], TODAY)
    assert d.action == "auto_bridge" and d.amount == D(295)  # $292 short of $500, rounded up to fives


def test_helping_keeps_the_helper_above_their_own_cushion() -> None:
    sam = helper("sam", 1000, 200)  # his balance never goes below $1,000
    assert decide(proj("maya", 208), [sam], TODAY).action == "auto_bridge"  # 1,000 - 100 ≥ his $300
    wary = replace(sam, projection=replace(sam.projection, floor=D(950)))
    assert decide(proj("maya", 208), [wary], TODAY).action == "no_safe_helper"  # 1,000 - 100 < $950


# ---------- the forecast and the API (demo mode, auth off) ----------
@pytest.fixture
def auth_off(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.auth import deps

    monkeypatch.setattr(deps, "config", lambda: None)
    monkeypatch.setattr(main, "auth_config", lambda: None)


def test_the_forecast_and_me_use_the_persons_own_amount(auth_off: None) -> None:
    assert client.get("/forecast?persona=maya").json()["safe_floor"] == 300
    r = client.put("/me/safe-floor", json={"persona": "maya", "amount": 100})
    assert r.status_code == 200 and r.json()["safe_floor"] == 100
    assert client.get("/forecast?persona=maya").json()["safe_floor"] == 100
    assert client.get("/me?persona=maya").json()["safe_floor"] == 100
    assert client.get("/forecast?persona=jordan").json()["safe_floor"] == 1500  # his own default; nobody else changes


def test_out_of_range_amounts_are_refused(auth_off: None) -> None:
    assert client.put("/me/safe-floor", json={"persona": "maya", "amount": -5}).status_code == 422
    assert client.put("/me/safe-floor", json={"persona": "maya", "amount": 99999}).status_code == 422


def test_unknown_people_are_refused_before_anything_is_saved(auth_off: None) -> None:
    assert client.put("/me/safe-floor", json={"persona": "nobody", "amount": 50}).status_code == 404
    assert prefs.floor("nobody") == prefs.DEFAULT_FLOOR


# ---------- who may change it ----------
def test_signed_out_you_cant_change_anyones(auth_on: None) -> None:  # noqa: F811
    assert client.put("/me/safe-floor", json={"persona": "maya", "amount": 50}).status_code == 401
    assert prefs.floor("maya") == prefs.DEFAULT_FLOOR


def test_signed_in_you_only_ever_change_your_own(auth_on: None) -> None:  # noqa: F811
    r = client.put("/me/safe-floor", json={"persona": "maya", "amount": 50}, headers=as_("sam"))
    assert r.status_code == 200 and r.json()["first_name"] == "Sam" and r.json()["safe_floor"] == 50
    assert prefs.floor("sam") == 50 and prefs.floor("maya") == prefs.DEFAULT_FLOOR


def test_reset_puts_everyone_back_to_the_default() -> None:
    prefs.set_floor("maya", 75)
    prefs.reset(["maya"])
    assert prefs.floor("maya") == prefs.DEFAULT_FLOOR


# ---------- review fixes: the floor can't be used against the family ----------
def test_a_decision_remembers_the_borrowers_floor() -> None:
    d = decide(replace(proj("maya", 208), floor=D(250)), [helper("sam", 5000, 100)], TODAY)
    assert d.action == "auto_bridge" and d.floor == D(250)


def test_raising_your_floor_after_being_helped_cant_stall_repayment() -> None:
    from app.safety_net import _repay_floor

    bridge = {"borrower_slug": "maya", "borrower_floor": D(300)}
    prefs.set_floor("maya", 5000)  # raised right after Sam helped
    assert _repay_floor(None, bridge) == D(300)  # repayment still only has to leave her $300
    prefs.set_floor("maya", 100)  # lowering it lets the money go back sooner
    assert _repay_floor(None, bridge) == D(100)
    assert _repay_floor(None, {"borrower_slug": "maya", "borrower_floor": None}) == D(100)  # older bridges


def test_with_real_transfers_on_an_anonymous_caller_cant_change_it(
    monkeypatch: pytest.MonkeyPatch, auth_off: None
) -> None:
    from app import data

    monkeypatch.setattr(data, "writes_enabled", lambda: True)
    r = client.put("/me/safe-floor", json={"persona": "maya", "amount": 0})
    assert r.status_code in (401, 503) and prefs.floor("maya") == prefs.DEFAULT_FLOOR

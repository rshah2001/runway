"""What Ask Runway may set up, and the switch that decides it: off, every action answers that it doesn't
have permission and where to do it by hand; on, each action is only a proposal the person approves."""

import dataclasses

import pytest
from fastapi.testclient import TestClient

from app import main, prefs
from app.agent import actions, tools
from app.agent import chat as agent
from tests.test_agent import TODAY

client = TestClient(main.app)


@pytest.fixture
def off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(prefs.DEFAULTS, "ai_actions", False)  # nobody has turned it on


@pytest.fixture
def auth_off(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.auth import deps

    monkeypatch.setattr(deps, "config", lambda: None)
    monkeypatch.setattr(main, "auth_config", lambda: None)


def _call(tool: str, persona: str = "maya", **args) -> dict:
    return tools.call(tool, args, TODAY, persona)


# ---------- the switch ----------
@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("propose_transfer", {}),
        ("send_money", {"person": "Sam", "amount": 20}),
        ("pay_back", {"person": "Sam", "amount": 40}),
        ("create_circle", {"name": "Roommates"}),
        ("share_circle_link", {"circle": "Family"}),
    ],
)
def test_off_every_action_says_no_permission_and_proposes_nothing(off: None, tool: str, args: dict) -> None:
    before = set(tools.PENDING)
    r = _call(tool, **args)
    assert r["error"] == "no_permission" and "Let Ask Runway set things up" in r["turn_it_on"]
    assert r["or_do_it_yourself"] == actions.DO_IT_YOURSELF[tool]
    assert set(tools.PENDING) == before


def test_off_reads_still_work(off: None) -> None:
    assert "lowest_balance" in _call("get_forecast")
    assert _call("my_circles")["ai_actions_allowed"] is False


@pytest.mark.parametrize(
    ("message", "where"),
    [
        ("Fix it", "Fix it button"),
        ("Pay Sam back $40", "Pay back"),
        ("Create a circle called Roommates", "New circle"),
        ("Ask Alex for $45 for concert tickets", "Family tab"),
    ],
)
def test_off_the_router_says_it_has_no_permission_and_where_to_go(off: None, message: str, where: str) -> None:
    r = agent.chat(message, persona="maya", today=TODAY)
    assert r.pending_action is None
    assert "don't have permission" in r.reply and "account menu" in r.reply and where in r.reply


def test_the_fix_it_button_works_with_the_switch_off(off: None) -> None:
    """The button is the person's own tap, not a request to the AI."""
    r = agent.fix(persona="maya", today=TODAY)
    assert r.pending_action is not None and r.pending_action.kind == "transfer"


def test_the_prompt_tells_gemini_whether_actions_are_on(off: None, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    class Capture:
        class interactions:  # noqa: N801 — mimics the SDK's client.interactions
            @staticmethod
            def create(**kw):
                seen.append(kw["system_instruction"])
                raise RuntimeError("stop after the first request")

    monkeypatch.setattr(agent, "RETRY_DELAY_S", 0)
    agent.chat("send Sam $20", persona="maya", client=Capture(), today=TODAY)
    assert agent.ACTIONS_OFF in seen[0]


def test_preferences_turn_it_on_for_yourself_only(off: None, auth_off: None) -> None:
    assert client.get("/me?persona=maya").json()["ai_actions"] is False
    r = client.put("/me/preferences", json={"persona": "maya", "ai_actions": True})
    assert r.status_code == 200 and r.json()["ai_actions"] is True and r.json()["alerts_only"] is False
    assert client.get("/me?persona=jordan").json()["ai_actions"] is False


# ---------- on: proposals only ----------
def test_send_money_proposes_to_someone_in_your_circles() -> None:
    r = _call("send_money", person="sam", amount=20, memo="pizza")
    action = tools.PENDING[r["action_id"]]
    assert action.kind == "person_send" and action.amount == 20.0 and action.status == "awaiting_approval"
    assert actions.details(action.id) == {"to": "sam", "memo": "pizza"}
    assert "nothing has happened" in r["status"]


def test_send_money_to_someone_outside_your_circles_proposes_nothing() -> None:
    r = _call("send_money", person="Priya", amount=20)
    assert "action_id" not in r and r["people_you_can_send_to"] == ["Alex", "Emma", "Jordan", "Sam"]


def test_an_amount_over_the_ceiling_is_an_error_not_a_card() -> None:
    assert "error" in _call("send_money", person="Sam", amount=50000)


def test_pay_back_part_or_all_of_what_is_out() -> None:
    part = _call("pay_back", person="Sam", amount=40)
    assert part["paying"] == "$40.00" and part["still_out_after"] == "$60.00"
    action = tools.PENDING[part["action_id"]]
    assert action.kind == "repay" and action.amount == 40.0 and action.description == "Pay Sam back $40.00 of $100.00"
    whole = _call("pay_back", person="Sam")
    assert tools.PENDING[whole["action_id"]].amount == 100.0
    assert "error" in _call("pay_back", person="Sam", amount=150)  # more than is out
    assert _call("pay_back", person="Alex")["nothing_out_from"] == "Alex"


def test_circle_actions_resolve_names_from_your_own_circles() -> None:
    invite = _call("invite_to_circle", circle="family", person="Alex")
    assert tools.PENDING[invite["action_id"]].kind == "circle_invite"
    assert actions.details(invite["action_id"]) == {"circle": "circle-family", "slug": "alex"}
    assert _call("leave_circle", circle="Chess club")["your_circles"] == ["Family", "Weekend crew"]
    assert tools.PENDING[_call("create_circle", name="Roommates")["action_id"]].kind == "circle_create"


def test_resume_support_only_for_paused_support() -> None:
    assert tools.PENDING[_call("resume_support", "sam", person="Jordan")["action_id"]].kind == "resume_support"
    assert _call("resume_support", "sam", person="Maya")["already"] == "on"


def test_approving_a_circle_action_carries_it_out_once(auth_off: None) -> None:
    r = _call("create_circle", name="Roommates")
    first = client.post(f"/actions/{r['action_id']}/approve")
    assert first.status_code == 200 and first.json()["status"] == "executed"
    assert client.post(f"/actions/{r['action_id']}/approve").status_code == 409  # no replays


def test_a_refusal_from_the_backend_reaches_the_person(auth_off: None, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.agent import execute

    def refuse(*_a):
        raise execute.ActionRefused("Only the person who made this circle can remove someone.")

    monkeypatch.setattr(execute, "run", refuse)
    r = _call("remove_from_circle", circle="Family", person="Emma")
    res = client.post(f"/actions/{r['action_id']}/approve")
    assert res.status_code == 422 and "Only the person who made this circle" in res.json()["detail"]
    assert tools.PENDING[r["action_id"]].status == "awaiting_approval"  # nothing happened: it can be tried later


def test_the_fix_route_returns_a_transfer_card(off: None, auth_off: None) -> None:
    r = client.post("/agent/fix", json={"persona": "maya"})  # no message: it's a button
    assert r.status_code == 200 and r.json()["pending_action"]["kind"] == "transfer"


def test_repay_route_takes_part_of_what_is_out(auth_off: None) -> None:
    r = client.post("/safety-net/bridges/demo-b1/repay", json={"amount": 40})
    assert r.status_code == 200 and r.json()["amount"] == 60.0 and r.json()["status"] == "active"
    assert client.post("/safety-net/bridges/demo-b1/repay").json()["status"] == "repaid"  # no body: all of it
    assert client.post("/safety-net/bridges/demo-b1/repay", json={"amount": 0.5}).status_code == 422


def test_pay_back_more_than_today_allows_makes_no_card_and_says_what_would_work(monkeypatch) -> None:
    from app.forecast import sources

    real = sources.load

    def tight(persona, today):
        d = real(persona, today)
        return dataclasses.replace(d, checking=d.safe_floor + 25.6)  # $25.60 above what they keep

    monkeypatch.setattr(sources, "load", tight)
    before = set(tools.PENDING)
    r = _call("pay_back", person="Sam", amount=40)
    assert r["goes_through_now"] is False and r["most_you_can_pay_now"] == "$25.00"
    assert set(tools.PENDING) == before


def test_one_approval_can_create_a_circle_and_invite_people() -> None:
    r = _call("create_circle", name="Roommates", invite=["Alex", "Sam", "Priya"])
    assert r["inviting"] == ["Alex", "Sam"] and r["not_on_runway"] == ["Priya"]
    assert actions.details(r["action_id"]) == {"name": "Roommates", "invite": ["alex", "sam"]}
    assert tools.PENDING[r["action_id"]].description == 'Create the circle "Roommates" and invite Alex and Sam'

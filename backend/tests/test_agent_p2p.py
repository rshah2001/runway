"""The agent's peer-to-peer tools: who owes you (read) and asking a contact to pay you back (write).

Expected figures come from the P2P data layer, not hard-coded, so these tests check that the tools
report it faithfully and that every share is computed in code. Approval goes through the real route.
"""

from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import data, main
from app.agent import chat as agent
from app.agent import tools
from tests.test_agent import FakeGemini, _calls, _text
from tests.test_auth_routes import as_, auth_on  # noqa: F401 — auth_on is a fixture used by name

TODAY = date(2026, 10, 16)
client = TestClient(main.app)


def _money(text: str) -> float:
    return float(text.replace("$", "").replace(",", ""))


@pytest.fixture
def created(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, ...]]:
    """Every P2P request the approve route creates, recorded instead of written."""
    calls: list[tuple[Any, ...]] = []
    real = data.p2p_request

    def record(slug: str, contact_id: str, amount: float, memo: str):
        calls.append((slug, contact_id, amount, memo))
        return real(slug, contact_id, amount, memo)

    monkeypatch.setattr(data, "p2p_request", record)
    return calls


# ---------- who owes me ----------


def test_who_owes_me_totals_are_computed_from_the_data_layer() -> None:
    summary = data.p2p_summary("maya")
    r = tools.who_owes_me(persona="maya", today=TODAY)
    open_requests = [q for q in summary.requests if q.status == "open"]
    assert r["open_count"] == len(open_requests) > 0
    assert r["total_owed_to_you"] == tools.money(sum(q.amount for q in open_requests))
    owed = {c.name: tools.money(c.owes_you) for c in summary.contacts if c.owes_you}
    assert {o["contact"]: o["owes_you"] for o in r["owed_by_contact"]} == owed  # agrees with GET /p2p
    first = r["open_requests"][0]
    assert first["days_open"] == max(0, (TODAY - open_requests[0].created).days)
    received = sum(p.amount for p in summary.payments[: tools.RECENT_PAYMENTS] if p.direction == "in")
    assert r["recently_received"] == tools.money(received)


def test_router_answers_who_owes_me_with_only_tool_figures(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    r = agent.chat("who owes me money?", persona="maya", today=TODAY)
    truth = tools.who_owes_me(persona="maya", today=TODAY)
    assert r.tool_calls == ["who_owes_me"] and r.pending_action is None
    assert truth["total_owed_to_you"] in r.reply and agent.grounded(r.reply, "who owes me money?", truth)


def test_an_invented_iou_figure_from_gemini_is_discarded() -> None:
    fake = FakeGemini(_calls(("who_owes_me", {})), _text("Alex owes you $500, chase him!"))
    r = agent.chat("who owes me?", persona="maya", client=fake, today=TODAY)
    assert "$500" not in r.reply and r.tool_calls == ["who_owes_me"]  # the router's grounded answer


def test_who_owes_me_for_an_unknown_persona_is_an_error() -> None:
    assert "error" in tools.call("who_owes_me", {}, TODAY, persona="mallory")


# ---------- split math, in code ----------


@pytest.mark.parametrize(
    ("total", "people", "share", "you_cover"),
    [
        (60, 3, 20.0, 20.0),  # $60 with 2 others
        (60, 2, 30.0, 30.0),
        (100, 3, 33.33, 33.34),  # the leftover cent stays with the user, so the parts add up
        (0.25, 2, 0.13, 0.12),  # half a cent rounds up, not to even
    ],
)
def test_split_share_rounds_to_cents(total: float, people: int, share: float, you_cover: float) -> None:
    assert tools.split_share(total, people) == (share, you_cover)
    assert round(share * (people - 1) + you_cover, 2) == total


@pytest.mark.parametrize("people", [1, 0, tools.MAX_SPLIT_PEOPLE + 1])
def test_split_needs_at_least_two_people(people: int) -> None:
    with pytest.raises(ValueError):
        tools.split_share(60, people)


def test_request_money_splits_the_bill_and_moves_nothing() -> None:
    r = tools.request_money("alex", total=60, people=3, memo="Dinner split", persona="maya", today=TODAY)
    assert (r["contact"], r["request"], r["you_cover"]) == ("Alex", "$20.00", "$20.00")
    action = tools.PENDING[r["action_id"]]
    assert action.kind == "p2p_request" and action.amount == 20.0 and action.status == "awaiting_approval"
    assert tools.persona_of(action.id) == "maya" and tools.p2p_details(action.id) == ("maya-alex", "Dinner split")


@pytest.mark.parametrize("args", [{"amount": 5000}, {"amount": 0}, {}, {"total": 60, "people": 1}])
def test_request_money_rejects_bad_amounts(args: dict[str, Any]) -> None:
    before = set(tools.PENDING)
    assert "error" in tools.call("request_money", {"contact": "Alex", **args}, TODAY, persona="maya")
    assert set(tools.PENDING) == before


def test_the_model_cannot_request_money_as_someone_else() -> None:
    r = tools.call("request_money", {"contact": "Alex", "amount": 5, "persona": "sam"}, TODAY, persona="maya")
    assert tools.persona_of(r["action_id"]) == "maya"


# ---------- unknown contacts: never invented ----------


def test_unknown_contact_creates_no_pending_action() -> None:
    before = set(tools.PENDING)
    r = tools.request_money("Bob", amount=20, persona="maya", today=TODAY)
    assert r["contact_found"] is False and r["your_contacts"] == ["Alex", "Priya"]
    assert set(tools.PENDING) == before


def test_al_is_not_alex() -> None:
    assert tools.request_money("Al", amount=20, persona="maya", today=TODAY)["contact_found"] is False


def test_router_asks_which_contact(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    before = set(tools.PENDING)
    r = agent.chat("ask Bob for $20", persona="maya", today=TODAY)
    assert r.pending_action is None and "Bob" in r.reply and "Alex and Priya" in r.reply
    assert set(tools.PENDING) == before


# ---------- the router and Gemini propose; nothing is sent ----------


@pytest.mark.parametrize(
    ("message", "amount"),
    [
        ("Split dinner $60 with Alex", 30.0),
        ("ask Alex for $45 for concert tickets", 45.0),
        ("split the $100 cab with alex and priya", 33.33),
        ("split $90 3 ways with alex", 30.0),
        ("request $12.50 from priya for coffee", 12.5),
    ],
)
def test_router_proposes_requests(monkeypatch: pytest.MonkeyPatch, message: str, amount: float) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    r = agent.chat(message, persona="maya", today=TODAY)
    assert r.tool_calls == ["request_money"] and r.pending_action is not None
    assert r.pending_action.kind == "p2p_request" and r.pending_action.amount == amount
    assert tools.money(amount) in r.reply and "until you approve" in r.reply


def test_gemini_request_surfaces_as_a_pending_action() -> None:
    fake = FakeGemini(
        _calls(("request_money", {"contact": "Alex", "total": 60, "people": 2})),
        _text("I can ask Alex for $30.00 — approve it?"),
    )
    r = agent.chat("split dinner $60 with Alex", persona="maya", client=fake, today=TODAY)
    assert r.pending_action is not None and r.pending_action.kind == "p2p_request"
    assert r.pending_action.amount == 30.0 and agent.persona_of(r.pending_action.id) == "maya"


# ---------- approval ----------


def test_approving_creates_exactly_one_request(created: list[tuple[Any, ...]]) -> None:
    reply = client.post("/agent/chat", json={"message": "Split dinner $60 with Alex", "persona": "maya"}).json()
    action = reply["pending_action"]
    assert action["kind"] == "p2p_request" and created == []  # proposing created nothing

    first = client.post(f"/actions/{action['id']}/approve")
    assert first.status_code == 200 and first.json()["status"] == "executed"
    assert created == [("maya", "maya-alex", 30.0, "Dinner split")]

    assert client.post(f"/actions/{action['id']}/approve").status_code == 409  # no replays
    assert len(created) == 1


def test_a_request_can_only_be_approved_by_whoever_it_was_proposed_for(
    auth_on: None,  # noqa: F811 — the imported fixture
    created: list[tuple[Any, ...]],
) -> None:
    r = tools.request_money("Alex", amount=45, memo="Concert tickets", persona="sam", today=TODAY)
    action_id = r["action_id"]
    assert client.post(f"/actions/{action_id}/approve", headers=as_("maya")).status_code == 403
    assert tools.PENDING[action_id].status == "awaiting_approval" and created == []  # refused, claimed nothing
    assert client.post(f"/actions/{action_id}/approve", headers=as_("sam")).status_code == 200
    assert created == [("sam", "sam-alex", 45.0, "Concert tickets")]


def test_a_contact_that_disappeared_fails_the_request_for_good(monkeypatch: pytest.MonkeyPatch) -> None:
    def gone(*_: Any) -> None:
        raise data.ContactNotFound("maya-alex")

    r = tools.request_money("Alex", amount=10, persona="maya", today=TODAY)
    monkeypatch.setattr(data, "p2p_request", gone)
    assert client.post(f"/actions/{r['action_id']}/approve").status_code == 404
    assert tools.PENDING[r["action_id"]].status == "failed"  # never approvable again

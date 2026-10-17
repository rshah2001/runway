"""Contract tests: every route answers in the shape the app expects.

These run in CI on every PR. When a mock is replaced with the real implementation, these must
still pass — that is what lets the app team keep working without changes.
"""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_reports_demo_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AUTH0_DOMAIN", raising=False)
    monkeypatch.delenv("AUTH0_AUDIENCE", raising=False)
    assert client.get("/health").json() == {"ok": True, "mode": "demo"}


def test_health_shows_which_auth0_tenant_and_api_tokens_must_come_from(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH0_DOMAIN", "https://tenant.example.auth0.com/")
    monkeypatch.setenv("AUTH0_AUDIENCE", "https://api.example")
    monkeypatch.setenv("AUTH0_PERSONAS", "maya=auth0|a,sam=auth0|b")
    monkeypatch.delenv("AUTH0_CIBA_CLIENT_ID", raising=False)
    auth = client.get("/health").json()["auth"]
    assert auth == {
        "issuer": "https://tenant.example.auth0.com/",
        "audience": "https://api.example",
        "linked_logins": 2,
    }


def test_personas_list_the_three_demo_stories() -> None:
    slugs = [p["slug"] for p in client.get("/personas").json()]
    assert slugs == ["maya", "jordan", "sam"]


def test_spending_shape_and_totals_add_up() -> None:
    body = client.get("/spending?month=2026-10").json()
    assert body["month"] == "2026-10"
    assert body["total"] == pytest.approx(sum(c["spent"] for c in body["categories"]))
    spent = [c["spent"] for c in body["categories"]]
    assert spent == sorted(spent, reverse=True)  # biggest category first
    dates = [t["date"] for t in body["transactions"]]
    assert dates == sorted(dates, reverse=True)  # newest first


@pytest.mark.parametrize("query", ["month=2026-13", "month=oct", "persona=Maya", "persona=../etc"])
def test_spending_rejects_bad_input(query: str) -> None:
    assert client.get(f"/spending?{query}").status_code == 422


def test_me_has_accounts() -> None:
    body = client.get("/me").json()
    assert body["first_name"]
    assert {a["type"] for a in body["accounts"]} >= {"Checking", "Savings"}


def test_forecast_shape_and_low_point() -> None:
    body = client.get("/forecast?days=30").json()
    assert len(body["points"]) == 31  # today + 30 days
    lowest = min(p["balance"] for p in body["points"])
    assert body["low"]["balance"] == lowest
    assert body["safe_floor"] > 0


@pytest.mark.parametrize("days", [0, 366, 10**9])
def test_forecast_rejects_out_of_range_days(days: int) -> None:
    assert client.get(f"/forecast?days={days}").status_code == 422


def test_simulated_purchase_lowers_the_floor() -> None:
    base = client.get("/forecast").json()["low"]["balance"]
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    after = client.post("/simulate", json={"amount": 50, "date": tomorrow}).json()["low"]["balance"]
    assert after == pytest.approx(base - 50)


def test_recurring_lists_subscriptions() -> None:
    body = client.get("/recurring").json()
    assert body and all(r["amount"] > 0 and r["interval_days"] > 0 for r in body)


def test_fix_it_creates_pending_action_and_approves_exactly_once() -> None:
    reply = client.post("/agent/chat", json={"message": "fix it"}).json()
    action = reply["pending_action"]
    assert action["status"] == "awaiting_approval"
    assert len(action["id"]) >= 16  # unguessable

    first = client.post(f"/actions/{action['id']}/approve")
    assert first.status_code == 200 and first.json()["status"] == "executed"
    assert client.post(f"/actions/{action['id']}/approve").status_code == 409  # no replays


def test_unknown_action_is_404() -> None:
    assert client.post("/actions/does-not-exist/approve").status_code == 404


def test_cors_only_allows_app_origins() -> None:
    allowed = client.get("/health", headers={"Origin": "http://localhost:8081"})
    blocked = client.get("/health", headers={"Origin": "https://evil.example"})
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:8081"
    assert "access-control-allow-origin" not in blocked.headers


def test_live_transfers_are_off_by_default() -> None:
    from app.config import get_settings

    assert get_settings().live_transfers is False  # real money moves only after Auth0 lands


def test_personas_have_ages() -> None:
    assert [(p["slug"], p["age"]) for p in client.get("/personas").json()] == [
        ("maya", 20),
        ("jordan", 40),
        ("sam", 60),
    ]


def test_p2p_summary_shape() -> None:
    body = client.get("/p2p?persona=maya").json()
    alex = next(c for c in body["contacts"] if c["name"] == "Alex")
    assert alex["owes_you"] == 45.0
    assert {p["direction"] for p in body["payments"]} <= {"in", "out"}
    assert body["requests"][0]["status"] == "open"


def test_p2p_send_and_request_in_demo_mode() -> None:
    sent = client.post("/p2p/send", json={"contact_id": "maya-alex", "amount": 20, "memo": "Pizza"}).json()
    assert sent["direction"] == "out" and sent["amount"] == 20 and sent["contact"] == "Alex"
    req = client.post("/p2p/requests", json={"contact_id": "maya-priya", "amount": 12.5, "memo": "Coffee"}).json()
    assert req["status"] == "open" and req["contact"] == "Priya"


def test_settling_an_open_request_marks_it_paid() -> None:
    assert client.post("/p2p/requests/demo-r1/settle").json()["status"] == "paid"
    assert client.post("/p2p/requests/nope/settle").status_code == 409


@pytest.mark.parametrize(
    "body",
    [
        {"contact_id": "maya-alex", "amount": 0, "memo": "x"},
        {"contact_id": "maya-alex", "amount": 5000, "memo": "x"},  # over the per-payment cap
        {"contact_id": "../etc", "amount": 5, "memo": "x"},
        {"contact_id": "maya-alex", "amount": 5, "memo": ""},
        {"persona": "Maya!", "contact_id": "maya-alex", "amount": 5, "memo": "x"},
    ],
)
def test_p2p_send_validates_input(body: dict) -> None:
    assert client.post("/p2p/send", json=body).status_code == 422


def test_safety_net_shows_the_lender_when_the_money_comes_back() -> None:
    sam = client.get("/safety-net?persona=sam").json()
    assert any(b["status"] == "repaid" and b["repaid_on"] for b in sam["lent"])
    assert any(b["status"] == "active" and b["due_date"] for b in sam["lent"])
    assert any("got your" in e["message"] for e in sam["events"])
    maya = client.get("/safety-net?persona=maya").json()
    assert maya["borrowed"][0]["lender"] == "sam" and maya["projected_low"]["balance"] < 300


def test_over_limit_bridge_waits_for_the_lenders_approval() -> None:
    jordan = client.get("/safety-net?persona=jordan").json()
    waiting = jordan["approvals_waiting"][0]
    assert waiting["status"] == "pending_approval" and waiting["approval_channel"] == "auth0_push"
    assert client.post(f"/safety-net/bridges/{waiting['id']}/approve").json()["status"] == "active"
    assert client.post("/safety-net/bridges/nope/approve").status_code == 409


def test_safety_net_run_reports_what_it_would_do() -> None:
    d = client.post("/safety-net/run").json()[0]
    assert d["action"] == "auto_bridge" and d["executed"] is False


@pytest.mark.parametrize(
    "body,status",
    [
        ({"lender": "sam", "borrower": "maya", "limit": 150}, 200),
        ({"lender": "sam", "borrower": "sam", "limit": 50}, 422),  # no limits for yourself
        ({"lender": "sam", "borrower": "maya", "limit": 5000}, 422),
        ({"lender": "sam", "borrower": "nobody", "limit": 50}, 404),
    ],
)
def test_lender_sets_limits(body: dict, status: int) -> None:
    assert client.put("/safety-net/limits", json=body).status_code == status


def test_approval_moves_the_money_of_the_persona_it_was_proposed_for(monkeypatch: pytest.MonkeyPatch) -> None:
    """A "fix it" proposed for Sam must move Sam's savings when approved — never the default Maya's."""
    from app import data
    from app.agent import tools
    from app.schemas import PendingAction

    moved = {}
    monkeypatch.setattr(
        data, "move_savings_to_checking", lambda amount, desc, slug="maya": moved.setdefault("slug", slug)
    )
    action = PendingAction(id="test-sam-fix", kind="transfer", description="Move $50 from Savings", amount=50)
    tools.PENDING[action.id], tools.ACTION_PERSONA[action.id] = action, "sam"
    assert client.post(f"/actions/{action.id}/approve").status_code == 200
    assert moved["slug"] == "sam"


def test_chat_passes_the_persona_to_the_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.agent import chat as agent
    from app.schemas import ChatResponse

    seen = {}
    monkeypatch.setattr(
        agent, "chat", lambda message, persona="maya": seen.setdefault("p", persona) and ChatResponse(reply="ok")
    )
    client.post("/agent/chat", json={"message": "hi", "persona": "jordan"})
    assert seen["p"] == "jordan"


def test_chat_rejects_a_bad_persona() -> None:
    assert client.post("/agent/chat", json={"message": "hi", "persona": "../x"}).status_code == 422

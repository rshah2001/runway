"""Contract tests: every route answers in the shape the app expects.

These run in CI on every PR. When a mock is replaced with the real implementation, these must
still pass — that is what lets the app team keep working without changes.
"""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_reports_demo_mode() -> None:
    assert client.get("/health").json() == {"ok": True, "mode": "demo"}


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

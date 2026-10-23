"""A visitor's own Gemini key: it runs that one request instead of ours, and a failing key is reported
to them — never silently replaced by our key."""

from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import main
from app.agent import chat as agent
from tests.test_agent import FakeGemini, _text

TODAY = date(2026, 10, 16)
KEY = "AIzaVisitorOwnKey_0123456789abcdef"
client = TestClient(main.app)


class KeyRejected(Exception):
    """Stands in for the SDK's errors, which carry the HTTP status as `code` or as `status_code`."""

    def __init__(self, code: int) -> None:
        super().__init__(f"HTTP {code}")
        if code % 2:
            self.status_code = code  # e.g. BadRequestError
        else:
            self.code = code  # e.g. APIError


class Failing:
    def __init__(self, code: int) -> None:
        self.code = code
        self.interactions = self

    def create(self, **_: Any) -> Any:
        raise KeyRejected(self.code)


@pytest.fixture
def clients(monkeypatch: pytest.MonkeyPatch) -> list[str | None]:
    """Which key each Gemini client was built with; the client itself answers 'All good.'."""
    built: list[str | None] = []

    def build(api_key: str | None = None) -> FakeGemini:
        built.append(api_key)
        return FakeGemini(_text("All good."))

    monkeypatch.setattr(agent, "_gemini_client", build)
    monkeypatch.setattr(agent, "RETRY_DELAY_S", 0)
    return built


def test_the_visitors_key_answers_instead_of_ours(clients: list[str | None], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "server-key")
    r = agent.chat("how am I doing?", persona="maya", today=TODAY, api_key=KEY)
    assert clients == [KEY]  # built with theirs only
    assert r.reply == "All good." and r.own_key == "used"


def test_without_a_visitor_key_nothing_changes(clients: list[str | None], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "server-key")
    r = agent.chat("how am I doing?", persona="maya", today=TODAY)
    assert clients == [None] and r.own_key is None  # None → our key from the environment


FAILURES = [(400, "rejected"), (401, "rejected"), (403, "rejected"), (429, "quota"), (503, "didn't answer")]


@pytest.mark.parametrize(("code", "says"), FAILURES)
def test_a_failing_key_is_reported_and_never_swapped_for_ours(
    code: int, says: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    built: list[str | None] = []

    def build(api_key: str | None = None) -> Failing:
        built.append(api_key)
        return Failing(code)

    monkeypatch.setenv("GEMINI_API_KEY", "server-key")
    monkeypatch.setattr(agent, "_gemini_client", build)
    monkeypatch.setattr(agent, "RETRY_DELAY_S", 0)
    r = agent.chat("how am I doing?", persona="maya", today=TODAY, api_key=KEY)
    assert built == [KEY]  # our key was never tried
    assert r.own_key == "failed" and says in (r.own_key_problem or "")
    assert r.reply  # the rule-based router still answered


def test_the_route_passes_the_header_through(clients: list[str | None]) -> None:
    body = {"message": "how am I doing?", "persona": "maya"}
    r = client.post("/agent/chat", json=body, headers={"X-Gemini-Key": KEY})
    assert r.status_code == 200 and r.json()["own_key"] == "used" and clients == [KEY]


@pytest.mark.parametrize("bad", ["short", "has spaces in it but is long enough", "x" * 201])
def test_the_route_refuses_something_that_isnt_a_key(bad: str, clients: list[str | None]) -> None:
    r = client.post("/agent/chat", json={"message": "hi", "persona": "maya"}, headers={"X-Gemini-Key": bad})
    assert r.status_code == 422 and clients == []

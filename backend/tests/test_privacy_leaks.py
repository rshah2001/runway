"""Two leaks found in the Runway 2.0 audit: an anonymous safety-net run that reported every person's
low balance, and supporter-facing messages that revealed when (and so why) someone runs short."""

from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import demo, main, safety_net
from app.safety_net import Decision
from tests.test_privacy_alerts import auth_off  # noqa: F401 (fixture, used by name)

client = TestClient(main.app)
SHORT_DAY = date(2026, 11, 5)
DUE = date(2026, 11, 6)


@pytest.mark.usefixtures("auth_off")
def test_anonymous_run_checks_only_one_persona(monkeypatch: pytest.MonkeyPatch) -> None:
    asked = []
    monkeypatch.setattr(main, "get_settings", lambda: SimpleNamespace(live=True))
    monkeypatch.setattr(main.data, "writes_enabled", lambda: False)
    monkeypatch.setattr(demo, "release", lambda: None)
    monkeypatch.setattr(safety_net, "run", lambda slugs=None: asked.append(slugs) or [])
    client.post("/safety-net/run")
    assert asked == [["maya"]]  # never None, which would run (and report) everyone


def _supporter_texts(monkeypatch: pytest.MonkeyPatch, action: str) -> list[str]:
    """Every message act() writes to the supporter's feed, with the database faked out."""
    to_supporter = []
    bridge = {
        "id": "bridge-1",
        "borrower_slug": "maya",
        "lender_slug": "sam",
        "borrower_name": "Maya",
        "lender_name": "Sam",
        "amount": D(100),
        "shortfall_date": SHORT_DAY,
        "due_date": DUE,
        "mode": "approval",
    }

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def commit(self):
            pass

    monkeypatch.setattr(safety_net.pool, "connection", lambda: Conn())
    monkeypatch.setattr(safety_net.safety_repo, "open_bridge_for_borrower", lambda c, s: None)
    monkeypatch.setattr(safety_net.safety_repo, "insert_bridge", lambda c, row: None)
    monkeypatch.setattr(safety_net.safety_repo, "bridge", lambda c, i: bridge)
    monkeypatch.setattr(safety_net, "_request_approval", lambda c, b: "in_app")
    monkeypatch.setattr(
        safety_net.safety_repo,
        "add_event",
        lambda c, who, kind, msg, bid: to_supporter.append(msg) if who == "sam" else None,
    )
    d = Decision("maya", action, "x", D(100), "sam", SHORT_DAY, D(208), DUE, D(300))
    safety_net.act(d)
    return to_supporter


def test_approval_request_never_tells_the_supporter_when_or_why(monkeypatch: pytest.MonkeyPatch) -> None:
    texts = _supporter_texts(monkeypatch, "needs_approval")
    assert texts, "the supporter is still told there is something to approve"
    for t in texts:
        assert "Nov 5" not in t and "208" not in t and "before" not in t

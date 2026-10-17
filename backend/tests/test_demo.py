"""Demo controls and early repayment: who may use them, and that the hold really stops automatic
bridges. Local keys, no network — the Nessie rebuild itself is stubbed."""

import threading

import pytest
from fastapi.testclient import TestClient

from app import demo, main, safety_views
from tests.test_auth_routes import as_, auth_on, real_money  # noqa: F401 (fixtures)

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def no_hold() -> None:
    demo.release()
    yield
    demo.release()


def test_hold_pauses_and_release_resumes() -> None:
    assert not demo.held()
    demo.hold(minutes=5)
    assert demo.held() and demo.hold_until() is not None
    demo.release()
    assert not demo.held() and demo.hold_until() is None


def test_while_held_the_background_pass_syncs_but_never_runs_the_safety_net(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import safety_net

    calls: list[str] = []
    monkeypatch.setattr(main, "sync_personas", lambda prepare: calls.append("sync"))
    monkeypatch.setattr(safety_net, "tick", lambda: calls.append("tick"))
    demo.hold(minutes=5)
    main.background_pass()
    assert calls == ["sync"]
    demo.release()
    main.background_pass()
    assert calls == ["sync", "sync", "tick"]


def test_only_one_reset_runs_at_a_time_and_it_holds_the_safety_net(monkeypatch: pytest.MonkeyPatch) -> None:
    gate = threading.Event()

    def slow_rebuild() -> None:
        gate.wait(5)

    monkeypatch.setattr(demo, "rebuild", slow_rebuild)
    assert demo.start_reset() is True
    assert demo.held()  # paused from the first second
    assert demo.start_reset() is False  # a second press while running is refused
    gate.set()
    for _ in range(200):
        if demo.status()["state"] == "done":
            break
        threading.Event().wait(0.01)
    assert demo.status()["state"] == "done" and demo.held()
    assert demo.start_reset() is True  # and a new one can start once it's done
    for _ in range(200):  # let it finish while the stub is still in place
        if demo.status()["state"] == "done" and demo._lock.acquire(blocking=False):
            demo._lock.release()
            break
        threading.Event().wait(0.01)


def test_a_failed_reset_reports_only_the_kind_of_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> None:
        raise RuntimeError("https://api.nessieisreal.com/accounts?key=SECRET")

    monkeypatch.setattr(demo, "rebuild", boom)
    assert demo.start_reset()
    for _ in range(200):
        if demo.status()["state"] == "failed":
            break
        threading.Event().wait(0.01)
    s = demo.status()
    assert s["state"] == "failed" and s["error"] == "RuntimeError" and "SECRET" not in str(s)


def test_the_demo_reset_needs_a_signed_in_demo_account(auth_on: None) -> None:  # noqa: F811
    assert client.post("/demo/reset").status_code == 401
    # signed in as a demo persona, but CI has no live Nessie: refused before anything starts
    assert client.post("/demo/reset", headers=as_("maya")).status_code == 503
    assert not demo.held()


def test_only_the_borrower_pays_a_bridge_back(auth_on: None, real_money: None) -> None:  # noqa: F811
    bridge = safety_views.demo_summary("maya").borrowed[0]
    url = f"/safety-net/bridges/{bridge.id}/repay"
    assert client.post(url).status_code == 401
    assert client.post(url, headers=as_("sam")).status_code == 403  # the lender can't "repay" for her
    r = client.post(url, headers=as_("maya"))
    assert r.status_code == 200 and r.json()["status"] == "repaid"


def test_paying_back_an_unknown_bridge_is_refused() -> None:
    assert client.post("/safety-net/bridges/bridge-nope/repay").status_code == 409

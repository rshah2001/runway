"""A Send tap retried by a flaky phone connection must pay once (defect 4 of the Runway 2.0 audit)."""

import pytest

from app import data
from tests.test_safety_flow import Nessie, Store


@pytest.fixture
def live_send(monkeypatch: pytest.MonkeyPatch):
    store, nessie, payments = Store(), Nessie(), {}
    monkeypatch.setattr(data, "_writes_enabled", lambda: True)
    monkeypatch.setattr(data.pool, "connection", lambda: store)
    monkeypatch.setattr(data.journal_repo, "claim", store.claim)
    monkeypatch.setattr(data.journal_repo, "finish", store.finish)
    monkeypatch.setattr(data.journal_repo, "get", lambda conn, key: store.journal.get(key))
    monkeypatch.setattr(
        data,
        "_persona",
        lambda conn, slug: {"slug": slug, "first_name": "Maya", "checking_id": "m", "customer_id": "c"},
    )
    monkeypatch.setattr(
        data, "_contact_for", lambda conn, slug, cid: {"id": cid, "first_name": "Alex", "checking_id": "a"}
    )
    monkeypatch.setattr(data.repo, "insert_p2p_payment", lambda conn, row: payments.setdefault(row["id"], row))
    monkeypatch.setattr(data.repo, "p2p_payment", lambda conn, pid: {**payments[pid], "contact_name": "Alex"})
    monkeypatch.setattr(data.NessieClient, "from_settings", classmethod(lambda cls: nessie))
    monkeypatch.setattr(data, "_resync", lambda *a: None)
    return store, nessie, payments


def test_same_client_key_pays_once(live_send) -> None:
    store, nessie, payments = live_send
    first = data.p2p_send("maya", "maya-alex", 20, "Pizza", client_key="tap-12345678")
    again = data.p2p_send("maya", "maya-alex", 20, "Pizza", client_key="tap-12345678")
    assert first.id == again.id and len(payments) == 1
    assert sum(1 for s in nessie.sent if s[0] == "transfer") == 1


def test_a_tap_still_in_flight_is_refused_not_repeated(live_send) -> None:
    store, nessie, _ = live_send
    store.journal["p2p:maya:tap-87654321"] = {"key": "p2p:maya:tap-87654321", "ref": "p2p-x", "state": "started"}
    with pytest.raises(data.PaymentInProgress):
        data.p2p_send("maya", "maya-alex", 20, "Pizza", client_key="tap-87654321")
    assert nessie.sent == []

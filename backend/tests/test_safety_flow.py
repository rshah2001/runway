"""The safety net's money states, end to end against an in-memory store and a fake Nessie: an
unclear outcome is reconciled and never retried; a clear "nothing moved" may be retried; a stuck move
is settled only when Nessie shows it happened."""

from datetime import date
from decimal import Decimal as D

import pytest

from app import safety_net
from app.nessie.client import NessieError

DUE = date(2026, 10, 23)


class Store:
    """Just enough of the bridges + journal tables for safety_net's money paths."""

    def __init__(self, status: str = "active"):
        self.bridge = {
            "id": "bridge-1",
            "borrower_slug": "maya",
            "lender_slug": "sam",
            "borrower_name": "Maya",
            "lender_name": "Sam",
            "amount": D(100),
            "status": status,
            "mode": "auto",
            "shortfall_date": DUE,
            "due_date": DUE,
            "agreement_version": 1,
        }
        self.agreement = {
            "supporter_consent_at": "yes",
            "recipient_consent_at": "yes",
            "revoked_at": None,
            "limit_amount": D(150),
            "enabled": True,
            "version": 1,
        }
        self.journal: dict[str, dict] = {}
        self.events: list[tuple[str, str]] = []
        self.locks: list[tuple[str, ...]] = []

    # ---- connection ----
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def commit(self):
        pass

    def rollback(self):
        pass

    # ---- safety_repo ----
    def transition(self, conn, bridge_id, frm, to, **fields):
        if self.bridge["status"] not in frm:
            return None
        self.bridge.update(status=to, **fields)
        return dict(self.bridge)

    def add_event(self, conn, slug, kind, message, bridge_id=None):
        self.events.append((slug, kind))

    # ---- journal_repo ----
    def claim(self, conn, key, kind, ref, frm, to, amount):
        if key in self.journal:
            return False
        self.journal[key] = dict(
            key=key, kind=kind, ref=ref, from_account=frm, to_account=to, amount=amount, state="started"
        )
        return True

    def finish(self, conn, key, state, transfer_id=None, deposit_id=None, error=None):
        row = self.journal.get(key)
        if row is None or row["state"] not in ("started", "unknown"):
            return False
        row.update(state=state, transfer_id=transfer_id, deposit_id=deposit_id)
        return True

    def for_ref(self, conn, ref, kind):
        return [r for r in self.journal.values() if r["ref"] == ref and r["kind"] == kind]

    def unresolved(self, conn, older_than):
        return [r for r in self.journal.values() if r["state"] in ("started", "unknown")]


class Nessie:
    def __init__(self, deposit_error=None, transfers=(), deposits=()):
        self.deposit_error, self.sent = deposit_error, []
        self._transfers, self._deposits = list(transfers), list(deposits)

    def create_transfer(self, account, amount, on, memo):
        self.sent.append(("transfer", account, memo))
        return {"_id": f"t{len(self.sent)}"}

    def create_deposit(self, account, amount, on, memo):
        self.sent.append(("deposit", account, memo))
        if self.deposit_error:
            raise self.deposit_error
        return {"_id": f"d{len(self.sent)}"}

    def delete_transfer(self, transfer_id):
        self.sent.append(("delete", transfer_id))

    def account(self, account_id):
        return {"_id": account_id}

    def transfers(self, account_id):
        return self._transfers

    def deposits(self, account_id):
        return self._deposits


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch):
    def install(store: Store, nessie: Nessie):
        people = {
            "maya": {"checking_id": "maya-chk", "customer_id": "c1"},
            "sam": {"checking_id": "sam-chk", "customer_id": "c2"},
        }
        monkeypatch.setattr(safety_net.pool, "connection", lambda: store)
        monkeypatch.setattr(safety_net.safety_repo, "transition", store.transition)
        monkeypatch.setattr(safety_net.safety_repo, "add_event", store.add_event)
        monkeypatch.setattr(safety_net.safety_repo, "bridge", lambda conn, bridge_id: dict(store.bridge))
        monkeypatch.setattr(safety_net.safety_repo, "lock_people", lambda conn, *slugs: store.locks.append(slugs))
        monkeypatch.setattr(safety_net.agreements_repo, "get", lambda conn, s, r: dict(store.agreement))
        monkeypatch.setattr(safety_net.journal_repo, "claim", store.claim)
        monkeypatch.setattr(safety_net.journal_repo, "finish", store.finish)
        monkeypatch.setattr(safety_net.journal_repo, "for_ref", store.for_ref)
        monkeypatch.setattr(safety_net.journal_repo, "unresolved", store.unresolved)
        monkeypatch.setattr(safety_net.repo, "persona", lambda conn, slug: people[slug])
        monkeypatch.setattr(safety_net.prefs, "setting", lambda *a, **k: True)
        monkeypatch.setattr(safety_net.NessieClient, "from_settings", classmethod(lambda cls: nessie))
        monkeypatch.setattr(safety_net, "sync_customer", lambda *a: None)

    return install


def test_repay_with_unclear_outcome_is_never_retried(wire) -> None:
    store, nessie = Store("active"), Nessie(deposit_error=NessieError("POST", "/d", 504, "timeout"))
    wire(store, nessie)
    assert safety_net._pay_back(store.bridge, early=False) is None
    assert store.bridge["status"] == "reconcile"
    assert store.journal["repay:bridge-1:1"]["state"] == "unknown"
    sends = len(nessie.sent)
    assert safety_net._pay_back(store.bridge, early=False) is None  # a second try sends nothing
    assert len(nessie.sent) == sends


def test_repay_that_certainly_moved_nothing_is_retried_under_a_new_key(wire) -> None:
    store, nessie = Store("active"), Nessie(deposit_error=NessieError("POST", "/d", 400, "bad"))
    wire(store, nessie)
    safety_net._pay_back(store.bridge, early=False)
    assert store.bridge["status"] == "repay_failed" and store.journal["repay:bridge-1:1"]["state"] == "not_made"
    nessie.deposit_error = None
    assert safety_net._pay_back(store.bridge, early=False)["status"] == "repaid"
    assert store.journal["repay:bridge-1:2"]["state"] == "succeeded"


def test_fund_with_unclear_outcome_becomes_active_once_nessie_shows_both_halves(wire) -> None:
    store = Store("pending_approval")
    nessie = Nessie(deposit_error=NessieError("POST", "/d", 0, "timeout"))
    wire(store, nessie)
    assert safety_net._fund("bridge-1") is None
    assert store.bridge["status"] == "reconcile"
    tag = "[rw:fund:bridge-1]"
    nessie._transfers = [{"id": "t9", "description": f"x {tag}", "amount": 10000}]
    nessie._deposits = [{"_id": "d9", "description": f"y {tag}", "amount": 10000}]
    assert safety_net.reconcile_pending() == 1
    assert store.bridge["status"] == "active" and store.bridge["out_transfer_id"] == "t9"


def test_a_stuck_move_with_nothing_in_nessie_waits_for_a_person(wire) -> None:
    store = Store("funding")
    store.journal["fund:bridge-1"] = dict(
        key="fund:bridge-1",
        kind="fund",
        ref="bridge-1",
        from_account="sam-chk",
        to_account="maya-chk",
        amount=100,
        state="started",
    )
    wire(store, Nessie())
    assert safety_net.reconcile_pending() == 0
    assert store.bridge["status"] == "reconcile" and store.journal["fund:bridge-1"]["state"] == "unknown"


def test_a_bridge_is_never_funded_twice(wire) -> None:
    store, nessie = Store("pending_approval"), Nessie()
    wire(store, nessie)
    assert safety_net._fund("bridge-1")["status"] == "active"
    store.bridge["status"] = "pending_approval"  # even if something put it back
    assert safety_net._fund("bridge-1") is None
    assert sum(1 for s in nessie.sent if s[0] == "transfer") == 1


def test_funding_takes_both_peoples_locks_before_claiming(wire) -> None:
    store = Store("pending_approval")
    wire(store, Nessie())
    safety_net._fund("bridge-1")
    assert store.locks and set(store.locks[0]) == {"sam", "maya"}


def test_lock_order_is_sorted_so_two_passes_cannot_deadlock() -> None:
    from app.db import safety_repo

    taken = []

    class Conn:
        def execute(self, sql, params=None):
            if params:
                taken.append(params[0])

    safety_repo.lock_people(Conn(), "sam", "maya", "sam")
    assert taken == ["runway:maya", "runway:sam"]


def test_a_revoked_agreement_stops_a_waiting_approval_from_moving_money(wire) -> None:
    store, nessie = Store("pending_approval"), Nessie()
    store.agreement.update(supporter_consent_at=None, recipient_consent_at=None, revoked_at="now", version=2)
    wire(store, nessie)
    assert safety_net._fund("bridge-1") is None
    assert store.bridge["status"] == "declined" and nessie.sent == []


def test_a_limit_change_after_the_request_means_nothing_moves(wire) -> None:
    store, nessie = Store("pending_approval"), Nessie()
    store.agreement["version"] = 2  # the supporter changed something after the bridge was asked for
    wire(store, nessie)
    assert safety_net._fund("bridge-1") is None and nessie.sent == []

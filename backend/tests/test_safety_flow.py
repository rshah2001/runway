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
        self.receiving: tuple[float | None, bool] = (None, True)  # the recipient's own limits
        self.others: list[dict] = []  # other open bridges

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
        monkeypatch.setattr(safety_net.repo, "receiving", lambda conn, slug: store.receiving)
        monkeypatch.setattr(safety_net.safety_repo, "open_bridges", lambda conn: store.others)
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


# ---------- re-validation under the lock (security review: decide-then-act gap) ----------
@pytest.fixture
def fresh_rows(monkeypatch: pytest.MonkeyPatch):
    rows = {"outstanding": [], "limit": {"enabled": True, "limit_amount": D(150), "outstanding": D(0)}, "cap": D(500)}
    monkeypatch.setattr(safety_net, "_consent_still_holds", lambda *a: True)
    monkeypatch.setattr(safety_net.safety_repo, "open_bridges", lambda conn: rows["outstanding"])
    monkeypatch.setattr(safety_net.safety_repo, "limits", lambda conn, lender, borrower: [rows["limit"]])
    monkeypatch.setattr(safety_net, "_exposure_limit", lambda conn, slug: rows["cap"])
    monkeypatch.setattr(safety_net.agreements_repo, "get", lambda conn, s, r: {"mode": rows.get("mode", "auto")})
    return rows


def test_a_share_that_still_fits_passes(fresh_rows) -> None:
    assert safety_net._still_safe(None, "sam", "maya", D(90), True, 1)


def test_exposure_used_up_meanwhile_blocks_the_share(fresh_rows) -> None:
    fresh_rows["outstanding"] = [{"borrower_slug": "jordan", "lender_slug": "sam", "amount": D(450)}]
    assert not safety_net._still_safe(None, "sam", "maya", D(90), True, 1)


def test_a_supporter_who_started_borrowing_meanwhile_never_lends(fresh_rows) -> None:
    fresh_rows["outstanding"] = [{"borrower_slug": "sam", "lender_slug": "emma", "amount": D(20)}]
    assert not safety_net._still_safe(None, "sam", "maya", D(90), True, 1)


def test_a_lowered_or_paused_limit_meanwhile_blocks_an_automatic_share(fresh_rows) -> None:
    fresh_rows["limit"] = {"enabled": True, "limit_amount": D(50), "outstanding": D(0)}
    assert not safety_net._still_safe(None, "sam", "maya", D(90), True, 1)
    assert safety_net._still_safe(None, "sam", "maya", D(90), False, 1)  # an approval may exceed the auto limit
    fresh_rows["limit"] = {"enabled": False, "limit_amount": D(150), "outstanding": D(0)}
    assert not safety_net._still_safe(None, "sam", "maya", D(90), True, 1)


# ---------- safe repayment ----------
@pytest.fixture
def repay_world(monkeypatch: pytest.MonkeyPatch):
    from tests.test_safety_net import proj

    world = {"balance": D(1500), "landed": True, "projection": proj("maya", 900, after_payday=900)}
    monkeypatch.setattr(safety_net, "_checking_balance", lambda conn, p: world["balance"])
    monkeypatch.setattr(safety_net.repo, "paycheck_landed", lambda conn, acct, since, at_least: world["landed"])
    monkeypatch.setattr(safety_net, "project", lambda conn, slug, today=None: world["projection"])
    return world


B = {"amount": D(100), "due_date": date(2026, 11, 6), "funded_at": None, "borrower_slug": "maya"}
MAYA = {"checking_id": "maya-chk"}


def test_repays_when_the_paycheck_landed_and_nothing_dips(repay_world) -> None:
    assert safety_net._safe_to_repay(None, B, MAYA, D(300), date(2026, 11, 6))


def test_no_verified_paycheck_means_no_repayment_even_with_enough_balance(repay_world) -> None:
    repay_world["landed"] = False
    assert not safety_net._safe_to_repay(None, B, MAYA, D(300), date(2026, 11, 6))


def test_a_repayment_that_would_cause_a_new_dip_waits(repay_world) -> None:
    from tests.test_safety_net import proj

    repay_world["projection"] = proj("maya", 350, after_payday=350)  # 350 - 100 < 300 within the week
    assert not safety_net._safe_to_repay(None, B, MAYA, D(300), date(2026, 11, 8))


def test_a_supporter_who_asks_to_approve_every_time_is_never_moved_automatically(fresh_rows) -> None:
    fresh_rows["mode"] = "approval"
    assert not safety_net._still_safe(None, "sam", "maya", D(90), True, 1)
    assert safety_net._still_safe(None, "sam", "maya", D(90), False, 1)  # asking them is still fine


def test_a_recipient_who_lowered_their_cap_meanwhile_gets_nothing_moved(wire) -> None:
    store, nessie = Store("pending_approval"), Nessie()
    store.receiving = (50.0, True)  # Maya now owes at most $50 at once; this bridge is $100
    wire(store, nessie)
    assert safety_net._fund("bridge-1") is None
    assert store.bridge["status"] == "declined" and nessie.sent == []


def test_one_person_only_meanwhile_stops_a_second_share(wire) -> None:
    store, nessie = Store("pending_approval"), Nessie()
    store.receiving = (None, False)
    store.others = [{"id": "bridge-2", "borrower_slug": "maya", "amount": D(45)}]  # Emma's share already open
    wire(store, nessie)
    assert safety_net._fund("bridge-1") is None and nessie.sent == []


def test_a_scoped_repayment_pass_touches_only_the_bridges_it_was_given(monkeypatch) -> None:
    mine = {"id": "bridge-mine", "due_date": date(2026, 10, 1), "status": "active"}
    other = {"id": "bridge-other", "due_date": date(2026, 10, 1), "status": "active"}
    paid = []

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(safety_net.pool, "connection", lambda: Conn())
    monkeypatch.setattr(safety_net.safety_repo, "outstanding_bridges", lambda conn: [mine, other])
    monkeypatch.setattr(safety_net.repo, "persona", lambda conn, slug: {})
    monkeypatch.setattr(safety_net, "_repay_floor", lambda conn, b: D(300))
    monkeypatch.setattr(safety_net, "_safe_to_repay", lambda *a: True)
    monkeypatch.setattr(safety_net, "_pay_back", lambda b, early: paid.append(b["id"]) or b)
    for b in (mine, other):
        b["borrower_slug"] = "maya"
    safety_net.repay_due(date(2026, 10, 2), only={"bridge-mine"})
    assert paid == ["bridge-mine"]


def test_a_supporters_fresh_forecast_is_rechecked_before_their_share_moves(monkeypatch) -> None:
    from tests.test_safety_net import helper

    sam = helper("sam", 390, 150).projection  # cautious balance $390, cushion $300: room $90
    monkeypatch.setattr(safety_net, "project", lambda conn, slug, today=None: sam)
    end = date(2026, 10, 26)
    assert safety_net._cash_still_safe(None, "sam", D(90), end, [])
    waiting = [{"lender_slug": "sam", "status": "pending_approval", "amount": D(40)}]  # promised elsewhere
    assert not safety_net._cash_still_safe(None, "sam", D(90), end, waiting)

"""Paying a bridge back in part: the part is its own closed row, the rest stays out in the status it had,
and every money-safety rule of a full repayment still holds (journal first, unclear = reconcile)."""

from decimal import Decimal as D

import pytest

from app import safety_net
from app.nessie.client import NessieError
from tests.test_safety_flow import Nessie, Store, wire  # noqa: F401 — wire is a fixture used by name


class PartStore(Store):
    """The Store from the safety-flow tests, plus `repay_part`."""

    def __init__(self, status: str = "active"):
        super().__init__(status)
        self.parts: list[dict] = []

    def repay_part(self, conn, bridge_id, frm, back_to, amount, t_id, d_id):
        if self.bridge["status"] not in frm or amount >= self.bridge["amount"]:
            return None
        self.bridge.update(amount=self.bridge["amount"] - amount, status=back_to)
        part = {**self.bridge, "id": f"{bridge_id}-p{len(self.parts) + 1}", "amount": amount, "status": "repaid"}
        part.update(part_of=bridge_id, back_transfer_id=t_id, back_deposit_id=d_id)
        self.parts.append(part)
        return dict(part)


@pytest.fixture
def parts(wire, monkeypatch: pytest.MonkeyPatch):  # noqa: F811 — the imported fixture
    def install(store: PartStore, nessie: Nessie) -> None:
        wire(store, nessie)
        monkeypatch.setattr(safety_net.safety_repo, "repay_part", store.repay_part)
        monkeypatch.setattr(safety_net.safety_repo, "part_count", lambda conn, bridge_id: len(store.parts))

    return install


def test_paying_part_leaves_the_rest_out_and_records_the_part(parts) -> None:
    store, nessie = PartStore("active"), Nessie()
    parts(store, nessie)
    row = safety_net._pay_back(store.bridge, early=True, amount=D(60))
    assert row["amount"] == D(60) and row["status"] == "repaid" and row["part_of"] == "bridge-1"
    assert store.bridge["amount"] == D(40) and store.bridge["status"] == "active"  # still out, same status
    assert store.journal["repay:bridge-1:1"]["amount"] == 60.0  # journalled for the part, not the whole
    assert ("maya", "repaid_part") in store.events and ("sam", "repaid_part") in store.events


def test_a_second_part_follows_a_first_that_landed(parts) -> None:
    store, nessie = PartStore("active"), Nessie()
    parts(store, nessie)
    safety_net._pay_back(store.bridge, early=True, amount=D(60))
    safety_net._pay_back(store.bridge, early=True, amount=D(25))  # a settled part doesn't block the next
    assert store.bridge["amount"] == D(15) and len(store.parts) == 2
    assert store.journal["repay:bridge-1:2"]["state"] == "succeeded"


def test_the_last_payment_closes_the_bridge(parts) -> None:
    store, nessie = PartStore("active"), Nessie()
    parts(store, nessie)
    safety_net._pay_back(store.bridge, early=True, amount=D(60))
    assert safety_net._pay_back(store.bridge, early=False)["status"] == "repaid"  # payday pays the $40 left
    assert store.journal["repay:bridge-1:2"]["amount"] == 40.0


def test_a_part_that_certainly_moved_nothing_leaves_the_bridge_as_it_was(parts) -> None:
    store = PartStore("active")
    parts(store, Nessie(deposit_error=NessieError("POST", "/d", 400, "bad")))
    assert safety_net._pay_back(store.bridge, early=True, amount=D(60)) is None
    # not "repay_failed": that means late, and this person was paying early by choice
    assert store.bridge["status"] == "active" and store.bridge["amount"] == D(100)


def test_a_part_with_an_unclear_outcome_is_reconciled_as_a_part(parts, monkeypatch: pytest.MonkeyPatch) -> None:
    store = PartStore("active")
    parts(store, Nessie(deposit_error=NessieError("POST", "/d", 504, "timeout")))
    assert safety_net._pay_back(store.bridge, early=True, amount=D(60)) is None
    assert store.bridge["status"] == "reconcile"
    monkeypatch.setattr(safety_net.reconcile, "resolve", lambda client, r: ("succeeded", "t9", "d9"))
    assert safety_net.reconcile_pending() == 1
    assert store.bridge["amount"] == D(40) and store.bridge["status"] == "active"  # not marked fully repaid
    assert store.parts[0]["back_transfer_id"] == "t9"


@pytest.fixture
def balance(parts, monkeypatch: pytest.MonkeyPatch):
    """repay_now with Maya's checking at `amount` and a $300 cushion."""

    def install(amount: str) -> PartStore:
        store = PartStore("active")
        parts(store, Nessie())
        monkeypatch.setattr(safety_net, "_checking_balance", lambda conn, persona: D(amount))
        monkeypatch.setattr(safety_net, "_repay_floor", lambda conn, b: D(300))
        return store

    return install


def test_repay_now_takes_any_amount_up_to_what_is_out(balance) -> None:
    balance("500")
    rest = safety_net.repay_now("bridge-1", D("60"))
    assert rest["amount"] == D(40) and rest["status"] == "active"  # the screen gets what's still out


@pytest.mark.parametrize("amount", ["0.50", "100.01", "-5"])
def test_repay_now_refuses_amounts_outside_one_dollar_to_what_is_out(balance, amount: str) -> None:
    balance("5000")
    with pytest.raises(safety_net.RepayRefused, match="from \\$1 up to the \\$100"):
        safety_net.repay_now("bridge-1", D(amount))


def test_repay_now_says_how_much_could_go_back_without_going_under_the_cushion(balance) -> None:
    store = balance("365.80")  # $65.80 above the $300 kept
    with pytest.raises(safety_net.RepayRefused, match="You could pay \\$65 now"):
        safety_net.repay_now("bridge-1", D(100))
    assert store.bridge["amount"] == D(100) and store.journal == {}  # nothing claimed, nothing journalled


def test_a_full_repayment_that_landed_is_never_paid_again_even_if_the_bridge_reopened(parts) -> None:
    """More successful attempts than recorded parts: a whole repayment already went through."""
    store, nessie = PartStore("active"), Nessie()
    parts(store, nessie)
    store.journal["repay:bridge-1:1"] = dict(
        key="repay:bridge-1:1", kind="repay", ref="bridge-1", amount=100.0, state="succeeded"
    )
    sends = len(nessie.sent)
    assert safety_net._pay_back(store.bridge, early=True, amount=D(40)) is None
    assert len(nessie.sent) == sends  # nothing sent

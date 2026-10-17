"""move_money must leave either nothing moved or a clearly flagged partial state — never a silent
double payment. Tested against a fake Nessie client."""

from datetime import date

import pytest

from app.nessie.client import NessieError
from app.nessie.moves import TransferNeedsReconciliation, TransferNotMade, move_money

ON = date(2026, 10, 17)


class FakeNessie:
    def __init__(self, transfer=None, deposit=None, delete=None):
        self.calls, self._transfer, self._deposit, self._delete = [], transfer, deposit, delete

    def create_transfer(self, account, amount, on, memo):
        self.calls.append(("transfer", account))
        if self._transfer:
            raise self._transfer
        return {"_id": "t1"}

    def create_deposit(self, account, amount, on, memo):
        self.calls.append(("deposit", account))
        if self._deposit:
            raise self._deposit
        return {"_id": "d1"}

    def delete_transfer(self, transfer_id):
        self.calls.append(("delete", transfer_id))
        if self._delete:
            raise self._delete


def test_happy_path_returns_both_ids() -> None:
    n = FakeNessie()
    assert move_money(n, "from", "to", 10, ON, "memo", "dep") == ("t1", "d1")
    assert n.calls == [("transfer", "from"), ("deposit", "to")]


def test_rejected_transfer_means_nothing_moved() -> None:
    with pytest.raises(TransferNotMade):
        move_money(FakeNessie(transfer=NessieError("POST", "/t", 400, "bad")), "a", "b", 10, ON, "m", "d")


@pytest.mark.parametrize("err", [NessieError("POST", "/t", 503, ""), NessieError("POST", "/t", 0, "timeout")])
def test_unclear_transfer_outcome_needs_reconciliation(err) -> None:
    with pytest.raises(TransferNeedsReconciliation):
        move_money(FakeNessie(transfer=err), "a", "b", 10, ON, "m", "d")


def test_failed_deposit_undoes_the_transfer() -> None:
    n = FakeNessie(deposit=NessieError("POST", "/d", 400, "bad"))
    with pytest.raises(TransferNotMade):
        move_money(n, "a", "b", 10, ON, "m", "d")
    assert ("delete", "t1") in n.calls


def test_failed_undo_is_flagged_never_hidden() -> None:
    n = FakeNessie(deposit=NessieError("POST", "/d", 400, "bad"), delete=NessieError("DELETE", "/t", 503, ""))
    with pytest.raises(TransferNeedsReconciliation):
        move_money(n, "a", "b", 10, ON, "m", "d")

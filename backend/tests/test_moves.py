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


# ---------- Runway 2.0: an unclear deposit is never "undone and safe to retry" ----------
@pytest.mark.parametrize("err", [NessieError("POST", "/d", 503, ""), NessieError("POST", "/d", 0, "timeout")])
def test_unclear_deposit_outcome_needs_reconciliation_and_keeps_the_transfer(err) -> None:
    n = FakeNessie(deposit=err)  # the deposit may have landed: undoing the transfer would pay the borrower for free
    with pytest.raises(TransferNeedsReconciliation):
        move_money(n, "a", "b", 10, ON, "m", "d")
    assert not any(c[0] == "delete" for c in n.calls)


def test_undo_of_a_transfer_that_is_already_gone_counts_as_undone() -> None:
    n = FakeNessie(deposit=NessieError("POST", "/d", 400, "bad"), delete=NessieError("DELETE", "/t", 404, "gone"))
    with pytest.raises(TransferNotMade):
        move_money(n, "a", "b", 10, ON, "m", "d")


def test_key_tags_both_memos() -> None:
    seen = []

    class Recording(FakeNessie):
        def create_transfer(self, account, amount, on, memo):
            seen.append(memo)
            return super().create_transfer(account, amount, on, memo)

        def create_deposit(self, account, amount, on, memo):
            seen.append(memo)
            return super().create_deposit(account, amount, on, memo)

    move_money(Recording(), "a", "b", 10, ON, "Safety net for Maya", "From Sam", key="fund:bridge-1")
    assert seen == ["Safety net for Maya [rw:fund:bridge-1]", "From Sam [rw:fund:bridge-1]"]


def test_amounts_are_whole_cents_and_at_least_one() -> None:
    n = FakeNessie()
    with pytest.raises(ValueError):
        move_money(n, "a", "b", 0.004, ON, "m", "d")
    assert n.calls == []

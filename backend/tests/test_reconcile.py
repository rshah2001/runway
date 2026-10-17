"""Reconciling a money move whose outcome was unclear. The only automatic verdict is "it happened"
(exactly one tagged transfer and one tagged deposit for the right amount). Everything else waits for a
person — absence of evidence is never treated as "nothing moved", because that verdict invites a retry."""

from app import reconcile
from app.nessie.moves import find_move

ROW = {"key": "fund:bridge-1", "from_account": "a", "to_account": "b", "amount": 100}
TAG = "[rw:fund:bridge-1]"


class Ledger:
    def __init__(self, transfers=(), deposits=(), missing=()):
        self._t, self._d, self._missing = list(transfers), list(deposits), set(missing)

    def account(self, account_id):
        return [] if account_id in self._missing else {"_id": account_id}

    def transfers(self, account_id):
        return self._t if account_id == "a" else []

    def deposits(self, account_id):
        return self._d if account_id == "b" else []


def t(desc, cents=10000, i="t1"):
    return {"id": i, "description": desc, "amount": cents}


def d(desc, cents=10000, i="d1"):
    return {"_id": i, "description": desc, "amount": cents}


def test_find_move_matches_the_tag_only() -> None:
    led = Ledger([t("Allowance"), t(f"Safety net {TAG}", i="t9")], [d(f"From Sam {TAG}", i="d9"), d("Paycheck")])
    assert find_move(led, "a", "b", "fund:bridge-1") == (["t9"], ["d9"])


def test_both_legs_once_for_the_right_amount_is_succeeded() -> None:
    led = Ledger([t(f"x {TAG}")], [d(f"y {TAG}")])
    assert reconcile.resolve(led, ROW) == ("succeeded", "t1", "d1")


def test_nothing_found_is_not_assumed_to_be_nothing_moved() -> None:
    assert reconcile.resolve(Ledger(), ROW)[0] == "reconcile"


def test_one_leg_only_needs_a_person() -> None:
    assert reconcile.resolve(Ledger([t(f"x {TAG}")], []), ROW)[0] == "reconcile"
    assert reconcile.resolve(Ledger([], [d(f"y {TAG}")]), ROW)[0] == "reconcile"


def test_wrong_amount_or_duplicates_need_a_person() -> None:
    assert reconcile.resolve(Ledger([t(f"x {TAG}", 9999)], [d(f"y {TAG}")]), ROW)[0] == "reconcile"
    two = Ledger([t(f"x {TAG}"), t(f"x {TAG}", i="t2")], [d(f"y {TAG}")])
    assert reconcile.resolve(two, ROW)[0] == "reconcile"


def test_a_deleted_account_is_never_read_as_nothing_moved() -> None:
    assert reconcile.resolve(Ledger([t(f"x {TAG}")], [d(f"y {TAG}")], missing={"a"}), ROW)[0] == "reconcile"

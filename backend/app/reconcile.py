"""Deciding what happened to a money move whose outcome was unclear (a timeout or 5xx from Nessie).

The only automatic verdict is "it happened": exactly one tagged transfer on the sender and one tagged
deposit on the receiver, both for the journaled amount. Anything else — nothing found, one half
found, duplicates, a wrong amount, an account that no longer exists — stays `reconcile` for a person
to settle. We never conclude "nothing moved" from absence, because that verdict is what invites a
retry, and a retry of a move that did land is a double payment.
"""

from typing import Literal

from app.nessie.client import NessieClient, to_cents
from app.nessie.moves import find_move

Verdict = Literal["succeeded", "reconcile"]


def _amount_cents(items: list[dict], wanted: str) -> int | None:
    match = next((i for i in items if (i.get("_id") or i.get("id")) == wanted), None)
    return int(match["amount"]) if match and match.get("amount") is not None else None


def resolve(nessie: NessieClient, row: dict) -> tuple[Verdict, str | None, str | None]:
    """(verdict, transfer_id, deposit_id) for a journal row with key, from_account, to_account, amount."""
    for account in (row["from_account"], row["to_account"]):
        if not nessie.account(account):  # Nessie answers 404 as [] — a deleted account is not "no move"
            return "reconcile", None, None
    transfers, deposits = find_move(nessie, row["from_account"], row["to_account"], row["key"])
    if len(transfers) != 1 or len(deposits) != 1:
        return "reconcile", None, None
    cents = to_cents(row["amount"])
    t_cents = _amount_cents(nessie.transfers(row["from_account"]), transfers[0])
    d_cents = _amount_cents(nessie.deposits(row["to_account"]), deposits[0])
    if t_cents != cents or d_cents != cents:
        return "reconcile", None, None
    return "succeeded", transfers[0], deposits[0]

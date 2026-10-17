"""Moving money between two Nessie accounts — used by "Fix it" (savings → checking), peer-to-peer
payments and the safety net.

Nessie transfers carry no destination, so a move is two writes: a transfer on the sender's account
and a deposit on the receiver's. Only a clear rejection (4xx) means a write did not happen; a timeout
or 5xx may have been applied. So a failure ends in exactly one of two states:
  * TransferNotMade            — nothing moved (or the outgoing half was certainly undone): safe to retry
  * TransferNeedsReconciliation — the outcome is unclear: never retry; app/reconcile.py checks Nessie

Nessie has no idempotency keys, so callers pass a `key` that is written into both memos as
`[rw:<key>]`. That tag is how reconciliation finds a move later (`find_move`).
"""

from datetime import date

from app.nessie.client import NessieClient, NessieError, from_cents, to_cents


class TransferNotMade(RuntimeError):
    """Nothing was written to Nessie (or it was fully undone): safe to let the user retry."""


class TransferNeedsReconciliation(RuntimeError):
    """Money may have partially moved. Never retry automatically — reconcile against Nessie first."""


def tag(key: str) -> str:
    return f"[rw:{key}]"


def _rejected(e: Exception) -> bool:
    """Only a 4xx is a clear "Nessie did not apply this"."""
    return isinstance(e, NessieError) and 400 <= e.status < 500


def move_money(
    nessie: NessieClient,
    from_account: str,
    to_account: str,
    amount: float,
    on: date,
    memo: str,
    deposit_memo: str,
    *,
    key: str | None = None,
) -> tuple[str, str]:
    """Transfer out of `from_account`, deposit into `to_account`. Returns (transfer_id, deposit_id)."""
    cents = to_cents(amount)  # one rounding, used for both halves, so they can never disagree
    if cents < 1:
        raise ValueError(f"amount must be at least one cent, got {amount!r}")
    amount = float(from_cents(cents))
    if key:
        memo, deposit_memo = f"{memo} {tag(key)}", f"{deposit_memo} {tag(key)}"
    try:
        transfer = nessie.create_transfer(from_account, amount, on, memo)
    except Exception as e:
        if _rejected(e):
            raise TransferNotMade(str(e)) from e
        raise TransferNeedsReconciliation(f"transfer outcome unknown: {e}") from e
    transfer_id = transfer.get("_id") or transfer.get("id", "")
    try:
        deposit = nessie.create_deposit(to_account, amount, on, deposit_memo)
    except Exception as deposit_error:
        if not _rejected(deposit_error):
            # the deposit may have landed: undoing the transfer now could credit the receiver for free
            raise TransferNeedsReconciliation(
                f"deposit outcome unknown after transfer {transfer_id}: {deposit_error}"
            ) from deposit_error
        try:
            nessie.delete_transfer(transfer_id)  # undo the outgoing half
        except Exception as undo_error:
            if not (isinstance(undo_error, NessieError) and undo_error.status == 404):  # 404: already gone
                raise TransferNeedsReconciliation(
                    f"deposit failed and transfer {transfer_id} could not be undone: {undo_error}"
                ) from deposit_error
        raise TransferNotMade(f"deposit failed; transfer {transfer_id} undone: {deposit_error}") from deposit_error
    return transfer_id, deposit.get("_id") or deposit.get("id", "")


def find_move(nessie: NessieClient, from_account: str, to_account: str, key: str) -> tuple[list[str], list[str]]:
    """Ids of every transfer on `from_account` and deposit on `to_account` tagged with `key`."""
    mark = tag(key)

    def ids(items: list[dict]) -> list[str]:
        return [i.get("_id") or i.get("id", "") for i in items or [] if mark in (i.get("description") or "")]

    return ids(nessie.transfers(from_account)), ids(nessie.deposits(to_account))

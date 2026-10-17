"""Moving money between two Nessie accounts — used by "Fix it" (savings → checking) and by
peer-to-peer payments (one person's checking → another's).

Nessie transfers carry no destination, so a move is two writes: a transfer on the sender's account
and a deposit on the receiver's. If the deposit fails, the transfer is deleted again, so a failure
leaves either nothing moved (safe to retry) or a clearly flagged partial state — never a silent
double payment.
"""

from datetime import date

from app.nessie.client import NessieClient, NessieError


class TransferNotMade(RuntimeError):
    """Nothing was written to Nessie (or it was fully undone): safe to let the user retry."""


class TransferNeedsReconciliation(RuntimeError):
    """Money may have partially moved. Never retry automatically — a human must check Nessie."""


def move_money(
    nessie: NessieClient, from_account: str, to_account: str, amount: float, on: date, memo: str, deposit_memo: str
) -> tuple[str, str]:
    """Transfer out of `from_account`, deposit into `to_account`. Returns (transfer_id, deposit_id)."""
    try:
        transfer = nessie.create_transfer(from_account, amount, on, memo)
    except Exception as e:
        # a write that timed out may still have landed; only a clear rejection means nothing moved
        if isinstance(e, NessieError) and 400 <= e.status < 500:
            raise TransferNotMade(str(e)) from e
        raise TransferNeedsReconciliation(f"transfer outcome unknown: {e}") from e
    transfer_id = transfer.get("_id") or transfer.get("id", "")
    try:
        deposit = nessie.create_deposit(to_account, amount, on, deposit_memo)
    except Exception as deposit_error:
        try:
            nessie.delete_transfer(transfer_id)  # undo the outgoing half
        except Exception as undo_error:
            raise TransferNeedsReconciliation(
                f"deposit failed and transfer {transfer_id} could not be undone: {undo_error}"
            ) from deposit_error
        raise TransferNotMade(f"deposit failed; transfer {transfer_id} undone: {deposit_error}") from deposit_error
    return transfer_id, deposit.get("_id") or deposit.get("id", "")

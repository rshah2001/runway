"""Nessie API client — owner: A.

MOCK: returns the demo persona's accounts. Replace with real calls to
http://api.nessieisreal.com (key from NESSIE_API_KEY), cached in Tiger Data.
See docs/NESSIE.md for the endpoint list.
"""
from app.schemas import Account, Me


def get_me() -> Me:
    return Me(
        customer_id="demo-maya",
        first_name="Maya",
        accounts=[
            Account(id="demo-chk", nickname="Everyday Checking", type="Checking", balance=680.00),
            Account(id="demo-sav", nickname="Savings", type="Savings", balance=1150.00),
            Account(id="demo-cc", nickname="Rewards credit card", type="Credit Card", balance=286.40),
        ],
    )


def create_transfer(from_account: str, to_account: str, amount: float, description: str) -> str:
    """MOCK — real version: POST /accounts/{from_account}/transfers. Returns the Nessie transfer id."""
    return f"mock-transfer-{from_account}-{to_account}-{amount:.2f}"

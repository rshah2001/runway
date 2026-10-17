"""Built-in demo data served when the API runs without keys (CI, offline teammates).

Numbers match the seeded "Maya" persona so the app looks the same in demo and live mode.
"""

import secrets
from datetime import date, timedelta

from app.schemas import (
    Account,
    CategorySpend,
    Contact,
    DailySpend,
    Me,
    P2PPayment,
    P2PRequest,
    P2PSummary,
    Persona,
    Spending,
    SpendingTransaction,
)

PERSONAS = [
    Persona(slug="maya", first_name="Maya", age=20, story="UF junior on a campus job — rent lands before payday"),
    Persona(
        slug="jordan", first_name="Jordan", age=40, story="Parent of two — subscriptions creep across the whole family"
    ),
    Persona(slug="sam", first_name="Sam", age=60, story="Pre-retiree with a pension on the way — healthy runway"),
]


def me(persona: str = "maya") -> Me:
    return Me(
        customer_id=f"demo-{persona}",
        first_name=next((p.first_name for p in PERSONAS if p.slug == persona), "Maya"),
        accounts=[
            Account(id="demo-chk", nickname="Everyday Checking", type="Checking", balance=680.00),
            Account(id="demo-sav", nickname="Savings", type="Savings", balance=1150.00),
            Account(id="demo-cc", nickname="Rewards credit card", type="Credit Card", balance=286.40),
        ],
    )


def spending(month: str) -> Spending:
    year, mon = map(int, month.split("-"))
    first = date(year, mon, 1)
    sample = [
        ("FreshMart", "Groceries", 46.20, 2),
        ("Chipotle", "Dining", 13.75, 3),
        ("Starbucks", "Dining", 6.45, 5),
        ("Shell", "Gas", 38.10, 6),
        ("Target", "Shopping", 27.99, 9),
        ("Spotify", "Subscriptions", 11.99, 8),
    ]
    txns = [
        SpendingTransaction(
            date=first + timedelta(days=d), merchant=m, category=c, amount=a, account="Rewards credit card"
        )
        for m, c, a, d in sample
    ]
    cats: dict[str, CategorySpend] = {}
    for t in txns:
        cs = cats.setdefault(t.category, CategorySpend(category=t.category, spent=0, purchases=0))
        cs.spent = round(cs.spent + t.amount, 2)
        cs.purchases += 1
    daily = [DailySpend(date=t.date, spent=t.amount) for t in txns]
    return Spending(
        month=month,
        total=round(sum(t.amount for t in txns), 2),
        categories=sorted(cats.values(), key=lambda c: -c.spent),
        daily=daily,
        transactions=sorted(txns, key=lambda t: t.date, reverse=True),
    )


def create_transfer(from_account: str, to_account: str, amount: float, description: str) -> str:
    return f"mock-transfer-{from_account}-{to_account}-{amount:.2f}"


def p2p_summary(persona: str = "maya") -> P2PSummary:
    today = date.today()
    alex, priya = f"{persona}-alex", f"{persona}-priya"
    return P2PSummary(
        contacts=[
            Contact(id=alex, name="Alex", relation="Roommate", owes_you=45.00),
            Contact(id=priya, name="Priya", relation="Friend", owes_you=0),
        ],
        payments=[
            P2PPayment(
                id="demo-p1",
                date=today - timedelta(days=2),
                direction="in",
                contact_id=priya,
                contact="Priya",
                amount=14.75,
                memo="Dinner split",
            ),
            P2PPayment(
                id="demo-p2",
                date=today - timedelta(days=5),
                direction="out",
                contact_id=alex,
                contact="Alex",
                amount=27.10,
                memo="Groceries split",
            ),
            P2PPayment(
                id="demo-p3",
                date=today - timedelta(days=11),
                direction="in",
                contact_id=alex,
                contact="Alex",
                amount=31.00,
                memo="Utilities split",
            ),
        ],
        requests=[
            P2PRequest(
                id="demo-r1",
                contact_id=alex,
                contact="Alex",
                amount=45.00,
                memo="Concert tickets 🎶",
                status="open",
                created=today - timedelta(days=4),
            ),
        ],
    )


def p2p_payment(contact_id: str, direction: str, amount: float, memo: str) -> P2PPayment:
    """What a payment looks like when real Nessie writes are off (nothing is persisted)."""
    name = contact_id.split("-", 1)[-1].title()
    return P2PPayment(
        id=f"demo-{secrets.token_hex(4)}",
        date=date.today(),
        direction=direction,
        contact_id=contact_id,
        contact=name,
        amount=amount,
        memo=memo,
    )


def p2p_request(contact_id: str, amount: float, memo: str) -> P2PRequest:
    name = contact_id.split("-", 1)[-1].title()
    return P2PRequest(
        id=f"demo-{secrets.token_hex(4)}",
        contact_id=contact_id,
        contact=name,
        amount=amount,
        memo=memo,
        status="open",
        created=date.today(),
    )

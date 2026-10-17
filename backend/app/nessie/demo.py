"""Built-in demo data served when the API runs without keys (CI, offline teammates).

Numbers match the seeded "Maya" persona so the app looks the same in demo and live mode.
"""

from datetime import date, timedelta

from app.schemas import Account, CategorySpend, DailySpend, Me, Persona, Spending, SpendingTransaction

PERSONAS = [
    Persona(slug="maya", first_name="Maya", story="UF junior on a campus job — rent lands before payday"),
    Persona(slug="jordan", first_name="Jordan", story="Grad student on a stipend — subscription creep"),
    Persona(slug="sam", first_name="Sam", story="New grad, first salary — healthy runway"),
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

"""The three demo personas. All people, balances and histories are fictional.

Maya's numbers match the demo mocks and prototype/index.html: her checking dips under the $300
safety floor right after rent, before the next payday — the overdraft story the demo is built on.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Habit:
    merchant: str
    per_week: float  # average visits per week
    low: float
    high: float
    account: str = "credit"  # "checking" (debit card) or "credit"


@dataclass(frozen=True)
class Bill:
    payee: str
    nickname: str
    amount: float
    day: int  # day of month it is paid, from checking


@dataclass(frozen=True)
class Subscription:
    merchant: str
    amount: float
    day: int  # monthly, on the credit card


@dataclass(frozen=True)
class Paycheck:
    amount: float
    label: str
    every_days: int | None = 14  # biweekly on Fridays; None = monthly on `day`
    day: int = 1


@dataclass(frozen=True)
class PersonaSpec:
    slug: str
    first_name: str
    last_name: str
    story: str
    checking: float  # balances as of today
    savings: float
    credit_owed: float
    paycheck: Paycheck
    bills: list[Bill] = field(default_factory=list)
    subscriptions: list[Subscription] = field(default_factory=list)
    habits: list[Habit] = field(default_factory=list)


# name → (category, street, lat, lng) — fictional addresses around Gainesville, FL
MERCHANTS: dict[str, tuple[str, str, float, float]] = {
    "FreshMart": ("Groceries", "University Ave", 29.6520, -82.3420),
    "Chipotle": ("Dining", "W 13th St", 29.6510, -82.3430),
    "Starbucks": ("Dining", "SW 2nd Ave", 29.6490, -82.3330),
    "Pizza Palace": ("Dining", "NW 16th Ave", 29.6670, -82.3410),
    "Taco Spot": ("Dining", "Archer Rd", 29.6290, -82.3740),
    "Shell": ("Gas", "Newberry Rd", 29.6600, -82.3880),
    "Target": ("Shopping", "Archer Rd", 29.6210, -82.3810),
    "Amazon": ("Shopping", "Online", 29.6516, -82.3248),
    "Movie Theater": ("Entertainment", "SW Archer Rd", 29.6230, -82.3770),
    "Campus Bookstore": ("Education", "Museum Rd", 29.6440, -82.3480),
    "Spotify": ("Subscriptions", "Online", 29.6516, -82.3248),
    "Netflix": ("Subscriptions", "Online", 29.6516, -82.3248),
    "Hulu": ("Subscriptions", "Online", 29.6516, -82.3248),
    "Max": ("Subscriptions", "Online", 29.6516, -82.3248),
    "Disney+": ("Subscriptions", "Online", 29.6516, -82.3248),
    "ChatGPT Plus": ("Subscriptions", "Online", 29.6516, -82.3248),
    "Audible": ("Subscriptions", "Online", 29.6516, -82.3248),
    "iCloud+": ("Subscriptions", "Online", 29.6516, -82.3248),
    "Gym Membership": ("Subscriptions", "NW 13th St", 29.6620, -82.3390),
}

PERSONAS: list[PersonaSpec] = [
    PersonaSpec(
        slug="maya",
        first_name="Maya",
        last_name="Demo",
        story="UF junior on a campus job — rent lands before payday",
        checking=680.00,
        savings=1150.00,
        credit_owed=286.40,
        paycheck=Paycheck(780.00, "Campus job paycheck"),
        bills=[
            Bill("Gainesville Apartments", "Rent", 650.00, 1),
            Bill("GRU Utilities", "Electric + internet", 62.00, 5),
            Bill("State Auto Insurance", "Car insurance", 108.00, 12),
            Bill("Mobile Carrier", "Phone bill", 35.00, 20),
            Bill("Rewards credit card", "Credit card payment", 286.40, 22),
        ],
        subscriptions=[
            Subscription("Spotify", 11.99, 8),
            Subscription("Netflix", 15.49, 14),
            Subscription("iCloud+", 9.99, 17),
        ],
        habits=[
            Habit("FreshMart", 1.3, 18, 72, "checking"),
            Habit("Chipotle", 0.9, 10, 16),
            Habit("Starbucks", 1.4, 5, 9),
            Habit("Pizza Palace", 0.4, 12, 24),
            Habit("Shell", 0.6, 28, 45, "checking"),
            Habit("Target", 0.4, 15, 60),
            Habit("Amazon", 0.5, 12, 48),
            Habit("Movie Theater", 0.2, 14, 28),
            Habit("Campus Bookstore", 0.15, 8, 40),
        ],
    ),
    PersonaSpec(
        slug="jordan",
        first_name="Jordan",
        last_name="Demo",
        story="Grad student on a stipend — subscription creep",
        checking=1240.00,
        savings=400.00,
        credit_owed=512.80,
        paycheck=Paycheck(2100.00, "Graduate stipend", every_days=None, day=1),
        bills=[
            Bill("Midtown Lofts", "Rent", 900.00, 1),
            Bill("GRU Utilities", "Utilities", 85.00, 6),
            Bill("Mobile Carrier", "Phone bill", 45.00, 18),
            Bill("Rewards credit card", "Credit card payment", 512.80, 25),
        ],
        subscriptions=[
            Subscription("Netflix", 15.49, 3),
            Subscription("Hulu", 17.99, 5),
            Subscription("Max", 16.99, 9),
            Subscription("Disney+", 13.99, 12),
            Subscription("Spotify", 11.99, 15),
            Subscription("ChatGPT Plus", 20.00, 19),
            Subscription("Gym Membership", 24.99, 21),
            Subscription("Audible", 14.95, 27),
        ],
        habits=[
            Habit("FreshMart", 1.0, 25, 80, "checking"),
            Habit("Starbucks", 2.0, 5, 8),
            Habit("Taco Spot", 1.0, 9, 18),
            Habit("Amazon", 1.0, 10, 55),
        ],
    ),
    PersonaSpec(
        slug="sam",
        first_name="Sam",
        last_name="Demo",
        story="New grad, first salary — healthy runway",
        checking=3820.00,
        savings=6500.00,
        credit_owed=340.25,
        paycheck=Paycheck(2600.00, "Salary"),
        bills=[
            Bill("Celebration Pointe Apartments", "Rent", 1400.00, 1),
            Bill("GRU Utilities", "Utilities", 120.00, 7),
            Bill("State Auto Insurance", "Car insurance", 140.00, 12),
            Bill("Auto Lender", "Car payment", 310.00, 15),
            Bill("Mobile Carrier", "Phone bill", 60.00, 20),
            Bill("Rewards credit card", "Credit card payment", 340.25, 24),
        ],
        subscriptions=[Subscription("Spotify", 11.99, 10), Subscription("Netflix", 15.49, 16)],
        habits=[
            Habit("FreshMart", 1.5, 30, 110, "checking"),
            Habit("Chipotle", 0.7, 11, 18),
            Habit("Taco Spot", 0.5, 12, 26),
            Habit("Shell", 0.8, 35, 55, "checking"),
            Habit("Target", 0.6, 20, 90),
            Habit("Movie Theater", 0.3, 15, 35),
        ],
    ),
]

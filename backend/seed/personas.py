"""The three demo personas — ages 20, 40 and 60. All people, balances and histories are fictional.

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
class Contact:
    """A friend or family member the persona sends money to / receives money from (peer-to-peer).
    Each contact is a real Nessie customer with a checking account."""

    key: str  # unique per persona, e.g. "alex"
    first_name: str
    last_name: str
    relation: str


@dataclass(frozen=True)
class P2PPattern:
    """A recurring peer-to-peer payment between the persona and a contact."""

    contact: str  # Contact.key
    direction: str  # "in" = contact pays the persona, "out" = persona pays the contact
    amount: float
    memo: str
    day: int | None = None  # monthly on this day…
    per_month: float = 0  # …or this many times a month, on random days (amount varies ±40%)


@dataclass(frozen=True)
class OpenRequest:
    """An unpaid IOU seeded for the demo: `contact` owes the persona `amount`."""

    contact: str
    amount: float
    memo: str
    days_ago: int


@dataclass(frozen=True)
class PersonaSpec:
    slug: str
    first_name: str
    last_name: str
    age: int
    story: str
    checking: float  # balances as of today
    savings: float
    credit_owed: float
    paycheck: Paycheck
    bills: list[Bill] = field(default_factory=list)
    subscriptions: list[Subscription] = field(default_factory=list)
    habits: list[Habit] = field(default_factory=list)
    contacts: list[Contact] = field(default_factory=list)
    p2p: list[P2PPattern] = field(default_factory=list)
    requests: list[OpenRequest] = field(default_factory=list)


# name → (category, street, lat, lng) — fictional addresses around Gainesville, FL
MERCHANTS: dict[str, tuple[str, str, float, float]] = {
    "FreshMart": ("Groceries", "University Ave", 29.6520, -82.3420),
    "Warehouse Club": ("Groceries", "Archer Rd", 29.6200, -82.3850),
    "Chipotle": ("Dining", "W 13th St", 29.6510, -82.3430),
    "Starbucks": ("Dining", "SW 2nd Ave", 29.6490, -82.3330),
    "Pizza Palace": ("Dining", "NW 16th Ave", 29.6670, -82.3410),
    "Taco Spot": ("Dining", "Archer Rd", 29.6290, -82.3740),
    "Family Diner": ("Dining", "NW 43rd St", 29.6810, -82.3870),
    "Shell": ("Gas", "Newberry Rd", 29.6600, -82.3880),
    "Target": ("Shopping", "Archer Rd", 29.6210, -82.3810),
    "Amazon": ("Shopping", "Online", 29.6516, -82.3248),
    "Hardware Store": ("Home", "NW 13th St", 29.6750, -82.3390),
    "Pharmacy": ("Health", "W University Ave", 29.6520, -82.3600),
    "Movie Theater": ("Entertainment", "SW Archer Rd", 29.6230, -82.3770),
    "Golf Club": ("Entertainment", "SW 20th Ave", 29.6300, -82.3990),
    "Campus Bookstore": ("Education", "Museum Rd", 29.6440, -82.3480),
    "Kids Activities": ("Education", "NW 8th Ave", 29.6600, -82.3500),
    "Spotify": ("Subscriptions", "Online", 29.6516, -82.3248),
    "Netflix": ("Subscriptions", "Online", 29.6516, -82.3248),
    "Hulu": ("Subscriptions", "Online", 29.6516, -82.3248),
    "Max": ("Subscriptions", "Online", 29.6516, -82.3248),
    "Disney+": ("Subscriptions", "Online", 29.6516, -82.3248),
    "ChatGPT Plus": ("Subscriptions", "Online", 29.6516, -82.3248),
    "Audible": ("Subscriptions", "Online", 29.6516, -82.3248),
    "iCloud+": ("Subscriptions", "Online", 29.6516, -82.3248),
    "Gym Membership": ("Subscriptions", "NW 13th St", 29.6620, -82.3390),
    "Kids Game Pass": ("Subscriptions", "Online", 29.6516, -82.3248),
    "News Digital": ("Subscriptions", "Online", 29.6516, -82.3248),
}

PERSONAS: list[PersonaSpec] = [
    PersonaSpec(
        slug="maya",
        first_name="Maya",
        last_name="Demo",
        age=20,
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
        contacts=[
            Contact("alex", "Alex", "Rivera", "Roommate"),
            Contact("priya", "Priya", "Shah", "Friend"),
        ],
        p2p=[
            P2PPattern("alex", "in", 31.00, "Utilities split", day=6),
            P2PPattern("alex", "out", 24.00, "Groceries split", per_month=2),
            P2PPattern("priya", "in", 16.00, "Dinner split", per_month=2),
        ],
        requests=[OpenRequest("alex", 45.00, "Concert tickets 🎶", days_ago=4)],
    ),
    PersonaSpec(
        slug="jordan",
        first_name="Jordan",
        last_name="Demo",
        age=40,
        story="Parent of two — subscriptions creep across the whole family",
        checking=2450.00,
        savings=3200.00,
        credit_owed=1284.60,
        paycheck=Paycheck(2900.00, "Salary"),
        bills=[
            Bill("Home Mortgage Co", "Mortgage", 1850.00, 1),
            Bill("Little Gators Daycare", "Daycare", 1100.00, 3),
            Bill("GRU Utilities", "Utilities", 210.00, 6),
            Bill("Auto Lender", "Car payment", 420.00, 15),
            Bill("Family Mobile", "Family phone plan", 140.00, 18),
            Bill("Rewards credit card", "Credit card payment", 1284.60, 25),
        ],
        subscriptions=[
            Subscription("Netflix", 22.99, 3),
            Subscription("Hulu", 17.99, 5),
            Subscription("Max", 16.99, 9),
            Subscription("Disney+", 13.99, 12),
            Subscription("Spotify", 16.99, 15),
            Subscription("Kids Game Pass", 9.99, 17),
            Subscription("Gym Membership", 49.99, 21),
            Subscription("Audible", 14.95, 27),
        ],
        habits=[
            Habit("Warehouse Club", 1.0, 120, 260, "checking"),
            Habit("FreshMart", 1.2, 30, 90, "checking"),
            Habit("Starbucks", 2.0, 5, 9),
            Habit("Family Diner", 0.8, 45, 85),
            Habit("Shell", 1.0, 45, 70, "checking"),
            Habit("Target", 0.8, 30, 140),
            Habit("Kids Activities", 0.3, 25, 90),
            Habit("Amazon", 1.2, 15, 80),
        ],
        contacts=[
            Contact("riley", "Riley", "Demo", "Partner"),
            Contact("dana", "Dana", "Brooks", "Soccer coach"),
        ],
        p2p=[
            P2PPattern("riley", "in", 550.00, "Half of daycare", day=2),
            P2PPattern("dana", "out", 60.00, "Kids soccer fees", day=10),
        ],
        requests=[OpenRequest("riley", 86.40, "Birthday party supplies", days_ago=2)],
    ),
    PersonaSpec(
        slug="sam",
        first_name="Sam",
        last_name="Demo",
        age=60,
        story="Pre-retiree with a pension on the way — healthy runway",
        checking=6200.00,
        savings=48000.00,
        credit_owed=612.35,
        paycheck=Paycheck(3100.00, "Consulting income"),
        bills=[
            Bill("Home Mortgage Co", "Mortgage", 980.00, 1),
            Bill("Health Insurance Co", "Health insurance", 640.00, 5),
            Bill("GRU Utilities", "Utilities", 165.00, 7),
            Bill("State Auto Insurance", "Car insurance", 120.00, 12),
            Bill("Mobile Carrier", "Phone bill", 60.00, 20),
            Bill("Rewards credit card", "Credit card payment", 612.35, 24),
        ],
        subscriptions=[
            Subscription("News Digital", 17.00, 4),
            Subscription("Netflix", 15.49, 16),
        ],
        habits=[
            Habit("FreshMart", 1.4, 40, 120, "checking"),
            Habit("Pharmacy", 0.5, 12, 65),
            Habit("Family Diner", 0.6, 30, 70),
            Habit("Shell", 0.7, 40, 60, "checking"),
            Habit("Hardware Store", 0.4, 20, 150),
            Habit("Golf Club", 0.5, 45, 90),
        ],
        contacts=[
            Contact("emma", "Emma", "Demo", "Daughter"),
            Contact("leo", "Leo", "Demo", "Grandson"),
        ],
        p2p=[
            P2PPattern("emma", "out", 150.00, "Help with grad school 🎓", day=1),
            P2PPattern("leo", "out", 25.00, "Allowance", per_month=1),
        ],
    ),
]

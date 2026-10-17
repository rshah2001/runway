"""The live data path, with the database replaced by rows shaped like `app.db.repo` returns them."""

from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.db import pool, repo
from app.forecast import sources

ET = ZoneInfo("America/New_York")
TODAY = date(2026, 10, 16)


@pytest.fixture
def live_db(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sources, "get_settings", lambda: SimpleNamespace(live=True))

    @contextmanager
    def fake_connection():
        yield object()

    monkeypatch.setattr(pool, "connection", fake_connection)
    monkeypatch.setattr(repo, "persona", lambda conn, slug: {"customer_id": "c-1"} if slug == "maya" else None)
    monkeypatch.setattr(
        repo,
        "accounts_with_balances",
        lambda conn, cid: [
            {"type": "Checking", "balance": Decimal("612.40")},
            {"type": "Savings", "balance": Decimal("1150.00")},
            {"type": "Credit Card", "balance": Decimal("286.40")},
        ],
    )
    monkeypatch.setattr(
        repo,
        "bills",
        lambda conn, cid: [
            {"nickname": "Rent", "amount": Decimal("650.00"), "recurring_day": 1, "account_type": "Checking"},
            {"nickname": "Card autopay", "amount": Decimal("40.00"), "recurring_day": 9, "account_type": "Credit Card"},
        ],
    )
    noon = datetime(2026, 10, 2, 12, tzinfo=ET)
    late_night_utc = datetime(2026, 10, 3, 3, 30, tzinfo=ZoneInfo("UTC"))  # still Oct 2 in Gainesville
    monkeypatch.setattr(
        repo,
        "transactions",
        lambda conn, cid, since, until: [
            {"ts": noon, "kind": "purchase", "amount": Decimal("-12.50"), "category": "Dining",
             "description": None, "status": "completed", "account_type": "Credit Card", "merchant": "Chipotle"},
            {"ts": late_night_utc, "kind": "deposit", "amount": Decimal("780.00"), "category": None,
             "description": "Campus job paycheck", "status": "completed", "account_type": "Checking", "merchant": None},
            {"ts": noon, "kind": "purchase", "amount": Decimal("-9.99"), "category": "Subscriptions",
             "description": None, "status": "pending", "account_type": "Credit Card", "merchant": "Spotify"},
        ],
    )  # fmt: skip


def test_live_rows_are_normalised(live_db: None) -> None:
    data = sources.load("maya", TODAY)
    assert (data.checking, data.savings) == (612.40, 1150.00)
    assert [(b.label, b.day, b.amount) for b in data.bills] == [("Rent", 1, 650.0)]  # checking bills only
    chipotle, paycheck = data.history  # the pending charge is left out until it posts
    assert (chipotle.label, chipotle.amount, chipotle.account) == ("Chipotle", -12.5, "Credit Card")
    assert (paycheck.label, paycheck.amount, paycheck.date) == ("Campus job paycheck", 780.0, date(2026, 10, 2))


def test_unknown_persona_is_not_silently_replaced(live_db: None) -> None:
    with pytest.raises(sources.UnknownPersona):
        sources.load("mallory", TODAY)


def test_a_database_failure_falls_back_to_the_seeded_persona(live_db: None, monkeypatch: pytest.MonkeyPatch) -> None:
    def down(*_: object) -> None:
        raise ConnectionError("database unreachable")

    monkeypatch.setattr(repo, "persona", down)
    assert sources.load("maya", TODAY) == sources._load_demo("maya", TODAY)

"""Nessie API client — owner: rshah2001.

Thin, typed wrapper over https://api.nessieisreal.com. Request shapes match the *current* API,
which differs from the old public SDKs (verified by probing, Oct 2026 — see docs/NESSIE.md):
  * transactions need status "pending" | "cancelled" | "completed"
  * transfers have no payee field — a transfer is a record on one account only
  * Nessie never changes balances itself; Runway computes live balances in Tiger Data
  * purchases, customers and merchants cannot be deleted (accounts, bills and transfers can)
  * balances and transaction amounts are silently truncated to whole dollars ($15.49 → 15), so
    Runway writes every money field as integer cents (minor units, as payment systems do) and
    converts back with `from_cents` on read
"""

import time
from datetime import date
from decimal import Decimal
from typing import Any

import httpx

from app.config import get_settings

RETRY_STATUS = {429, 500, 502, 503, 504}
JSON = dict[str, Any]


def to_cents(dollars: float | Decimal) -> int:
    return int((Decimal(str(dollars)) * 100).quantize(Decimal(1)))


def from_cents(cents: float | int | str) -> Decimal:
    return (Decimal(str(cents)) / 100).quantize(Decimal("0.01"))


class NessieError(RuntimeError):
    """Nessie rejected a request (4xx) or stayed unavailable after retries."""

    def __init__(self, method: str, path: str, status: int, body: str):
        super().__init__(f"Nessie {method} {path} → {status}: {body[:300]}")
        self.status = status


class NessieClient:
    def __init__(self, api_key: str, base_url: str, *, timeout: float = 30, retries: int = 3, transport=None):
        self._http = httpx.Client(base_url=base_url, params={"key": api_key}, timeout=timeout, transport=transport)
        self._retries = retries

    @classmethod
    def from_settings(cls) -> "NessieClient":
        s = get_settings()
        return cls(s.nessie_api_key, s.nessie_base_url)

    def _request(self, method: str, path: str, json: JSON | None = None) -> Any:
        """Send a request, retrying transient failures; unwrap `objectCreated` on creates."""
        for attempt in range(self._retries + 1):
            try:
                r = self._http.request(method, path, json=json)
            except httpx.TransportError as e:
                if attempt == self._retries:
                    raise NessieError(method, path, 0, str(e)) from e
            else:
                if r.status_code not in RETRY_STATUS:
                    break
                if attempt == self._retries:
                    raise NessieError(method, path, r.status_code, r.text)
            time.sleep(0.5 * 2**attempt)

        if method == "GET" and r.status_code == 404:  # Nessie answers "No X found" with 404 on empty lists
            return []
        if r.status_code >= 400:
            raise NessieError(method, path, r.status_code, r.text)
        if not r.content:
            return None
        body = r.json()
        return body.get("objectCreated", body) if isinstance(body, dict) else body

    # ---------- reads ----------
    def customers(self) -> list[JSON]:
        return self._request("GET", "/customers")

    def accounts(self, customer_id: str) -> list[JSON]:
        return self._request("GET", f"/customers/{customer_id}/accounts")

    def account(self, account_id: str) -> JSON:
        return self._request("GET", f"/accounts/{account_id}")

    def purchases(self, account_id: str) -> list[JSON]:
        return self._request("GET", f"/accounts/{account_id}/purchases")

    def deposits(self, account_id: str) -> list[JSON]:
        return self._request("GET", f"/accounts/{account_id}/deposits")

    def withdrawals(self, account_id: str) -> list[JSON]:
        return self._request("GET", f"/accounts/{account_id}/withdrawals")

    def transfers(self, account_id: str) -> list[JSON]:
        return self._request("GET", f"/accounts/{account_id}/transfers")

    def bills(self, account_id: str) -> list[JSON]:
        return self._request("GET", f"/accounts/{account_id}/bills")

    def merchants(self) -> list[JSON]:
        return self._request("GET", "/merchants")

    # ---------- writes ----------
    def create_customer(self, first_name: str, last_name: str, address: JSON) -> JSON:
        return self._request(
            "POST", "/customers", {"first_name": first_name, "last_name": last_name, "address": address}
        )

    def create_account(self, customer_id: str, type_: str, nickname: str, balance: float) -> JSON:
        body = {"type": type_, "nickname": nickname, "rewards": 0, "balance": to_cents(balance)}
        return self._request("POST", f"/customers/{customer_id}/accounts", body)

    def delete_account(self, account_id: str) -> None:
        self._request("DELETE", f"/accounts/{account_id}")

    def create_merchant(self, name: str, category: str, address: JSON, lat: float, lng: float) -> JSON:
        body = {"name": name, "category": category, "address": address, "geocode": {"lat": lat, "lng": lng}}
        return self._request("POST", "/merchants", body)

    def create_purchase(self, account_id: str, merchant_id: str, amount: float, on: date, description: str) -> JSON:
        body = {
            "merchant_id": merchant_id,
            "medium": "balance",
            "purchase_date": on.isoformat(),
            "amount": to_cents(amount),
            "status": "completed",  # never omit: a status-less purchase breaks GET .../purchases
            "description": description,
        }
        return self._request("POST", f"/accounts/{account_id}/purchases", body)

    def create_deposit(self, account_id: str, amount: float, on: date, description: str) -> JSON:
        body = {
            "medium": "balance",
            "transaction_date": on.isoformat(),
            "amount": to_cents(amount),
            "status": "completed",
            "description": description,
        }
        return self._request("POST", f"/accounts/{account_id}/deposits", body)

    def create_transfer(self, account_id: str, amount: float, on: date, description: str) -> JSON:
        """Record money leaving `account_id`. Nessie transfers carry no destination."""
        body = {"transaction_date": on.isoformat(), "status": "completed", "amount": to_cents(amount)}
        return self._request("POST", f"/accounts/{account_id}/transfers", {**body, "description": description})

    def delete_transfer(self, transfer_id: str) -> None:
        self._request("DELETE", f"/transfers/{transfer_id}")

    def create_bill(
        self, account_id: str, payee: str, nickname: str, amount: float, *, status: str, payment_date: date, day: int
    ) -> JSON:
        body = {
            "status": status,  # "recurring" for upcoming bills, "completed" for paid history
            "payee": payee,
            "nickname": nickname,
            "payment_date": payment_date.isoformat(),
            "recurring_date": day,
            "payment_amount": to_cents(amount),
        }
        return self._request("POST", f"/accounts/{account_id}/bills", body)

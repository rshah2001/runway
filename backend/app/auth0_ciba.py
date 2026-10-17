"""Auth0 push approval via CIBA (Client-Initiated Backchannel Authentication) — "Auth0 for AI Agents"
asynchronous authorization: the agent asks, the lender approves on their own phone.

Off unless configured (see docs/SAFETY_NET.md for the Auth0 tenant setup):
  AUTH0_DOMAIN, AUTH0_CIBA_CLIENT_ID, AUTH0_CIBA_CLIENT_SECRET,
  AUTH0_CIBA_USERS="sam=auth0|abc123,jordan=auth0|def456"   (persona → Auth0 user id)
"""

import json
import os
import re
from dataclasses import dataclass
from typing import Literal

import httpx

Answer = Literal["approved", "pending", "denied", "expired"]


@dataclass(frozen=True)
class Config:
    domain: str
    client_id: str
    client_secret: str
    users: dict[str, str]  # persona slug → Auth0 user id


def config() -> Config | None:
    domain, cid, secret = (
        os.getenv(k, "") for k in ("AUTH0_DOMAIN", "AUTH0_CIBA_CLIENT_ID", "AUTH0_CIBA_CLIENT_SECRET")
    )
    users = dict(pair.split("=", 1) for pair in os.getenv("AUTH0_CIBA_USERS", "").split(",") if "=" in pair)
    if not (domain and cid and secret and users):
        return None
    return Config(domain, cid, secret, {k.strip(): v.strip() for k, v in users.items()})


def binding_message(text: str) -> str:
    """Auth0 shows this on the phone; it allows only a small character set and 64 characters."""
    return re.sub(r"[^A-Za-z0-9 +\-_.,:#]", "", text)[:64].strip()


def start(cfg: Config, user_id: str, message: str, *, transport=None) -> str:
    """Send the push. Returns the auth_req_id to poll."""
    hint = json.dumps({"format": "iss_sub", "iss": f"https://{cfg.domain}/", "sub": user_id})
    with httpx.Client(transport=transport, timeout=15) as http:
        r = http.post(
            f"https://{cfg.domain}/bc-authorize",
            data={
                "client_id": cfg.client_id,
                "client_secret": cfg.client_secret,
                "scope": "openid",
                "login_hint": hint,
                "binding_message": binding_message(message),
                "requested_expiry": "300",
            },
        )
    r.raise_for_status()
    return r.json()["auth_req_id"]


def poll(cfg: Config, auth_req_id: str, *, transport=None) -> Answer:
    with httpx.Client(transport=transport, timeout=15) as http:
        r = http.post(
            f"https://{cfg.domain}/oauth/token",
            data={
                "grant_type": "urn:openid:params:grant-type:ciba",
                "auth_req_id": auth_req_id,
                "client_id": cfg.client_id,
                "client_secret": cfg.client_secret,
            },
        )
    if r.status_code == 200:
        return "approved"
    error = r.json().get("error", "") if r.headers.get("content-type", "").startswith("application/json") else ""
    if error in ("authorization_pending", "slow_down"):
        return "pending"
    if error == "access_denied":
        return "denied"
    if error == "expired_token":
        return "expired"
    r.raise_for_status()
    raise RuntimeError(f"unexpected Auth0 CIBA response {r.status_code}: {error}")

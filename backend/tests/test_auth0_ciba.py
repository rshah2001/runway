"""Auth0 push approval client against a fake Auth0 (no network)."""

import json
from urllib.parse import parse_qs

import httpx
import pytest

from app import auth0_ciba

CFG = auth0_ciba.Config("tenant.us.auth0.com", "cid", "secret", {"sam": "auth0|sam"})


def test_config_is_off_unless_fully_set(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in ("AUTH0_DOMAIN", "AUTH0_CIBA_CLIENT_ID", "AUTH0_CIBA_CLIENT_SECRET", "AUTH0_CIBA_USERS"):
        monkeypatch.delenv(k, raising=False)
    assert auth0_ciba.config() is None
    monkeypatch.setenv("AUTH0_DOMAIN", "t.auth0.com")
    monkeypatch.setenv("AUTH0_CIBA_CLIENT_ID", "c")
    monkeypatch.setenv("AUTH0_CIBA_CLIENT_SECRET", "s")
    monkeypatch.setenv("AUTH0_CIBA_USERS", "sam=auth0|1, jordan=auth0|2")
    assert auth0_ciba.config().users == {"sam": "auth0|1", "jordan": "auth0|2"}


def test_binding_message_fits_auth0_rules() -> None:
    msg = auth0_ciba.binding_message("Approve $150 for Maya 🎶 back Nov 06 — thanks! " * 3)
    assert len(msg) <= 64 and "$" not in msg and "🎶" not in msg


def test_start_sends_the_push_for_the_right_user() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["form"] = {k: v[0] for k, v in parse_qs(request.read().decode()).items()}
        return httpx.Response(200, json={"auth_req_id": "req-1", "expires_in": 300, "interval": 5})

    assert auth0_ciba.start(CFG, "auth0|sam", "Approve 150", transport=httpx.MockTransport(handler)) == "req-1"
    assert seen["url"] == "https://tenant.us.auth0.com/bc-authorize"
    assert json.loads(seen["form"]["login_hint"])["sub"] == "auth0|sam"
    assert seen["form"]["scope"] == "openid" and seen["form"]["binding_message"] == "Approve 150"


@pytest.mark.parametrize(
    "status,body,answer",
    [
        (200, {"access_token": "x"}, "approved"),
        (400, {"error": "authorization_pending"}, "pending"),
        (400, {"error": "slow_down"}, "pending"),
        (403, {"error": "access_denied"}, "denied"),
        (400, {"error": "expired_token"}, "expired"),
    ],
)
def test_poll_maps_auth0_answers(status: int, body: dict, answer: str) -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(status, json=body))
    assert auth0_ciba.poll(CFG, "req-1", transport=transport) == answer

"""Auth0 token verification with locally generated keys — no network, no real tenant."""

import base64
import hashlib
import hmac
import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import deps, tokens
from app.auth.tokens import PERSONA_CLAIM, AuthConfig, AuthError, User

CFG = AuthConfig(domain="runway-test.us.auth0.com", audience="https://api.runway.test", personas={"auth0|sam": "sam"})
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PUBLIC_PEM = KEY.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)


def _tenant_key(_: str) -> object:
    return KEY.public_key()


def _token(key=KEY, alg: str = "RS256", **overrides: object) -> str:
    now = int(time.time())
    claims = {"iss": CFG.issuer, "aud": CFG.audience, "sub": "auth0|maya", "iat": now, "exp": now + 600}
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm=alg)


# ---------- verify ----------


def test_valid_token_and_persona_claim() -> None:
    claims = tokens.verify(_token(**{PERSONA_CLAIM: "maya"}), CFG, _tenant_key)
    assert tokens.user_from_claims(claims, CFG) == User("auth0|maya", "maya")


def test_persona_falls_back_to_the_configured_map() -> None:
    claims = tokens.verify(_token(sub="auth0|sam"), CFG, _tenant_key)
    assert tokens.user_from_claims(claims, CFG).persona == "sam"


def test_unlinked_user_has_no_persona() -> None:
    claims = tokens.verify(_token(sub="auth0|stranger"), CFG, _tenant_key)
    assert tokens.user_from_claims(claims, CFG).persona is None


@pytest.mark.parametrize(
    "bad",
    [
        _token(key=OTHER_KEY),  # signed by someone else
        _token(aud="https://some-other-api"),
        _token(iss="https://evil.example/"),
        _token(exp=int(time.time()) - 3600, iat=int(time.time()) - 7200),  # expired
        _token(sub=None),  # no subject
        _token(exp=None),  # never expires
        "not-a-jwt",
    ],
)
def test_bad_tokens_are_rejected(bad: str) -> None:
    with pytest.raises(AuthError):
        tokens.verify(bad, CFG, _tenant_key)


def test_algorithm_confusion_is_rejected() -> None:
    # classic attack: HS256 "signed" with the server's public key, hoping it is used as the HMAC secret.
    # Built by hand because PyJWT refuses to create such a token.
    def b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    claims = {"iss": CFG.issuer, "aud": CFG.audience, "sub": "auth0|maya", "iat": int(time.time()), "exp": 9999999999}
    signing_input = f"{b64(json.dumps({'alg': 'HS256', 'typ': 'JWT'}).encode())}.{b64(json.dumps(claims).encode())}"
    forged = f"{signing_input}.{b64(hmac.new(PUBLIC_PEM, signing_input.encode(), hashlib.sha256).digest())}"
    with pytest.raises(AuthError):
        tokens.verify(forged, CFG, lambda _: PUBLIC_PEM)


def test_unsigned_token_is_rejected() -> None:
    unsigned = jwt.encode({"sub": "auth0|maya", "aud": CFG.audience, "iss": CFG.issuer}, None, algorithm="none")
    with pytest.raises(AuthError):
        tokens.verify(unsigned, CFG, _tenant_key)


def test_expired_session_has_a_friendly_message() -> None:
    with pytest.raises(AuthError, match="expired"):
        tokens.verify(_token(exp=int(time.time()) - 3600, iat=int(time.time()) - 7200), CFG, _tenant_key)


@pytest.mark.parametrize("header", [None, "", "Bearer", "Bearer   ", "Basic abc", _token()])
def test_header_must_be_a_bearer_token(header: str | None) -> None:
    with pytest.raises(AuthError):
        tokens.user_from_header(header, CFG, _tenant_key)


def test_config_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AUTH0_DOMAIN", raising=False)
    assert tokens.config() is None
    monkeypatch.setenv("AUTH0_DOMAIN", "https://runway-test.us.auth0.com/")
    monkeypatch.setenv("AUTH0_AUDIENCE", "https://api.runway.test")
    monkeypatch.setenv("AUTH0_PERSONAS", "maya=auth0|a, sam=auth0|b,broken")
    cfg = tokens.config()
    assert cfg and cfg.issuer == "https://runway-test.us.auth0.com/"
    assert cfg.personas == {"auth0|a": "maya", "auth0|b": "sam"}


# ---------- FastAPI dependencies ----------


def _app() -> TestClient:
    app = FastAPI()

    @app.get("/whose")
    def whose(user: deps.CurrentUser, persona: str = "maya") -> dict:
        return {"persona": deps.persona_for(user, persona)}

    @app.post("/move/{owner}")
    def move(owner: str, user: deps.CurrentUser) -> dict:
        deps.require_owner(user, owner)
        return {"ok": True}

    return TestClient(app)


@pytest.fixture
def auth_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(deps, "config", lambda: CFG)
    real = tokens.user_from_header
    monkeypatch.setattr(deps, "user_from_header", lambda h, cfg: real(h, cfg, _tenant_key))


def _bearer(**claims: object) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(**claims)}"}


def test_auth_off_keeps_todays_behaviour(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(deps, "config", lambda: None)
    client = _app()
    assert client.get("/whose?persona=sam").json() == {"persona": "sam"}
    assert client.post("/move/sam").status_code == 200


def test_signed_in_user_only_ever_sees_their_own_persona(auth_on: None) -> None:
    client = _app()
    maya = _bearer(**{PERSONA_CLAIM: "maya"})
    assert client.get("/whose?persona=sam", headers=maya).json() == {"persona": "maya"}  # query can't switch user
    assert client.get("/whose", headers=_bearer(sub="auth0|sam")).json() == {"persona": "sam"}


def test_only_the_owner_can_move_money(auth_on: None) -> None:
    client = _app()
    maya = _bearer(**{PERSONA_CLAIM: "maya"})
    assert client.post("/move/maya", headers=maya).status_code == 200
    assert client.post("/move/sam", headers=maya).status_code == 403


def test_missing_or_bad_token_is_401_when_auth_is_on(auth_on: None) -> None:
    client = _app()
    r = client.get("/whose")
    assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"
    assert client.get("/whose", headers={"Authorization": f"Bearer {_token(key=OTHER_KEY)}"}).status_code == 401


def test_unlinked_account_is_403(auth_on: None) -> None:
    assert _app().get("/whose", headers=_bearer(sub="auth0|stranger")).status_code == 403

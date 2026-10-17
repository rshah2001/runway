"""Auth0 access-token verification — owner: Patil-Hemangi.

The app signs in with Auth0 and sends `Authorization: Bearer <access token>` on every request. This
module checks that token and works out which persona the signed-in person is, so money-moving routes
act for the person who is actually logged in — not whoever the `?persona=` query names.

Checks, in order: the token is RS256 (fixed, so an HS256 token signed with our public key, or an
unsigned "none" token, is rejected), its signature matches a key from the tenant's JWKS, and its
issuer, audience and expiry are right. Nothing is trusted from the token before those pass.

Auth is off unless AUTH0_DOMAIN and AUTH0_AUDIENCE are set (CI, offline laptops): routes then keep
using `?persona=` exactly as before.
"""

import os
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import jwt

ALGORITHMS = ["RS256"]  # never derived from the token header
PERSONA_CLAIM = "https://runway.app/persona"  # set by an Auth0 Action; Auth0 requires namespaced claims
LEEWAY_SECONDS = 30  # tolerate small clock drift between Auth0 and the server

KeyResolver = Callable[[str], Any]  # token → public key; injectable so tests need no network


class AuthError(Exception):
    """The request's token can't be trusted. The message is safe to return to the client."""


@dataclass(frozen=True)
class AuthConfig:
    domain: str
    audience: str
    personas: dict[str, str]  # Auth0 user id → persona slug, for users without the persona claim

    @property
    def issuer(self) -> str:
        return f"https://{self.domain}/"


@dataclass(frozen=True)
class User:
    sub: str  # Auth0 user id, e.g. "auth0|65f…"
    persona: str | None  # None: signed in, but not linked to a persona


def _parse_personas(raw: str) -> dict[str, str]:
    """'maya=auth0|abc,sam=auth0|def' → {'auth0|abc': 'maya', 'auth0|def': 'sam'}."""
    pairs = (item.split("=", 1) for item in raw.split(",") if "=" in item)
    return {sub.strip(): slug.strip() for slug, sub in pairs if slug.strip() and sub.strip()}


def config() -> AuthConfig | None:
    domain = os.getenv("AUTH0_DOMAIN", "").strip().removeprefix("https://").rstrip("/")
    audience = os.getenv("AUTH0_AUDIENCE", "").strip()
    if not (domain and audience):
        return None
    return AuthConfig(domain, audience, _parse_personas(os.getenv("AUTH0_PERSONAS", "")))


@lru_cache(maxsize=4)
def _jwks_client(domain: str) -> jwt.PyJWKClient:
    # caches the key set and refetches on an unknown key id, so Auth0 key rotation just works
    return jwt.PyJWKClient(f"https://{domain}/.well-known/jwks.json", timeout=5)


def _tenant_key(cfg: AuthConfig) -> KeyResolver:
    return lambda token: _jwks_client(cfg.domain).get_signing_key_from_jwt(token).key


def verify(token: str, cfg: AuthConfig, key_for: KeyResolver | None = None) -> dict[str, Any]:
    """The token's claims, if it is a valid access token for this API; otherwise AuthError."""
    try:
        key = (key_for or _tenant_key(cfg))(token)
        return jwt.decode(
            token,
            key,
            algorithms=ALGORITHMS,
            audience=cfg.audience,
            issuer=cfg.issuer,
            leeway=LEEWAY_SECONDS,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except jwt.ExpiredSignatureError:
        raise AuthError("Your session expired. Sign in again.") from None
    except (jwt.PyJWTError, ValueError):  # bad signature, wrong audience/issuer, unknown key, malformed
        raise AuthError("Sign in again.") from None


def user_from_claims(claims: dict[str, Any], cfg: AuthConfig) -> User:
    sub = claims["sub"]
    persona = claims.get(PERSONA_CLAIM) or cfg.personas.get(sub)
    return User(sub=sub, persona=persona if isinstance(persona, str) else None)


def user_from_header(authorization: str | None, cfg: AuthConfig, key_for: KeyResolver | None = None) -> User:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AuthError("Sign in to continue.")
    return user_from_claims(verify(token.strip(), cfg, key_for), cfg)

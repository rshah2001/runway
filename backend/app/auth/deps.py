"""FastAPI dependencies that put the signed-in user on a route — owner: Patil-Hemangi.

Usage in main.py (the data team wires these in):

    from app.auth.deps import CurrentUser, persona_for, require_owner

    @app.get("/forecast")
    def forecast(user: CurrentUser, ..., persona: str = PERSONA):
        persona = persona_for(user, persona)          # signed in: always their own data

    @app.post("/actions/{action_id}/approve")
    def approve(action_id: str, user: CurrentUser):
        require_owner(user, agent.persona_of(action_id))   # 403 unless it's their money

With auth off (no AUTH0_DOMAIN/AUTH0_AUDIENCE), `current_user` returns None and both helpers fall
back to today's behaviour, so CI and offline demos keep working unchanged.
"""

from typing import Annotated

from fastapi import Depends, Header, HTTPException

from app.auth.tokens import AuthError, User, config, user_from_header


def current_user(authorization: str | None = Header(default=None)) -> User | None:
    """The signed-in user, None if auth is off; 401 if auth is on and the token is missing or bad."""
    cfg = config()
    if cfg is None:
        return None
    try:
        return user_from_header(authorization, cfg)
    except AuthError as e:
        raise HTTPException(401, str(e), headers={"WWW-Authenticate": "Bearer"}) from None


# the type a route parameter uses to receive the signed-in user (None when auth is off)
CurrentUser = Annotated[User | None, Depends(current_user)]


def _linked(user: User) -> str:
    if user.persona is None:
        raise HTTPException(403, "This account isn't linked to a Runway profile yet.")
    return user.persona


def persona_for(user: User | None, requested: str) -> str:
    """Whose data a read shows. Signed in: always the user's own persona, whatever the query says, so
    a reader can never see someone else's money. Auth off: the persona the request names."""
    return _linked(user) if user is not None else requested


def require_owner(user: User | None, owner: str) -> None:
    """403 unless the signed-in user owns the money being moved: approving a transfer, setting a
    safety-net limit, answering a bridge request. Auth off: allowed, as today."""
    if user is not None and _linked(user) != owner:
        raise HTTPException(403, "Only the account owner can do that.")

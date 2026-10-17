"""Runway API — owner: rshah2001. Routes are thin: each one delegates to the module its owner maintains.

Run:  uvicorn app.main:app --reload --port 8000   (docs at http://localhost:8000/docs)
"""

import asyncio
import contextlib
import logging
import os
import threading
from contextlib import asynccontextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from app import data, safety_views
from app.agent import chat as agent
from app.auth.deps import OptionalUser, persona_for, require_owner
from app.auth.tokens import User
from app.auth.tokens import config as auth_config
from app.config import get_settings
from app.db import pool
from app.db import schema as db_schema
from app.forecast import engine
from app.ingest import sync_personas
from app.schemas import (
    Bridge,
    ChatRequest,
    ChatResponse,
    Forecast,
    Me,
    P2PPayment,
    P2PRequest,
    P2PSend,
    P2PSummary,
    PendingAction,
    Persona,
    Recurring,
    SafetyDecision,
    SafetyLimit,
    SafetyNetSummary,
    SetLimit,
    SimulateRequest,
    Spending,
)
from app.sync_loop import run_periodically

log = logging.getLogger("runway")
PERSONA = Query(data.DEFAULT_PERSONA, pattern=r"^[a-z]{1,32}$", description="demo persona slug, e.g. maya")

# ---------- who may do what ----------
# Reads: signed in → always your own persona (persona_for ignores ?persona=); signed out → the demo
#        persona named in the request, so the site stays browsable without an account.
# Money: with real transfers on (LIVE_TRANSFERS=1) you must be signed in AND own the money; with them
#        off nothing real moves, so anyone may run the simulation — but a signed-in user still only
#        ever acts as themselves.


def authorize_money(user: User | None, owner: str | None) -> None:
    if user is not None:
        require_owner(user, owner or "")
    elif data.writes_enabled():
        if auth_config() is None:  # never move real money for an anonymous caller
            raise HTTPException(503, "Real transfers need sign-in, and sign-in isn't configured")
        raise HTTPException(401, "Sign in to move money", headers={"WWW-Authenticate": "Bearer"})


def background_pass() -> None:
    """Every interval: pull Nessie into Tiger Data, then let the safety net act (repayments,
    push approvals, new bridges) — the last part only when real writes are on."""
    sync_personas(prepare=False)
    from app import demo, safety_net

    if demo.held():  # a demo reset paused automatic bridges so the dip is still there on stage
        return

    safety_net.tick()


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings, sync_task = get_settings(), None
    if settings.live:
        try:
            with pool.connection() as conn:
                db_schema.apply(conn)
        except Exception:  # keep serving (reads fall back to demo data); /health shows the problem
            log.exception("could not apply the database schema at startup")
        if settings.sync_interval > 0:
            sync_task = asyncio.create_task(run_periodically(background_pass, settings.sync_interval, initial_delay=15))
    yield
    if sync_task:
        sync_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sync_task
    pool.close()


app = FastAPI(title="Runway API", lifespan=lifespan)

# only the app's own origins may call the API; set CORS_ORIGINS (comma-separated) when deploying
ALLOWED_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:8081,http://localhost:19006").split(",")
app.add_middleware(
    CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_methods=["GET", "POST", "PUT"], allow_headers=["*"]
)


@app.get("/health")
def health() -> dict:
    report = data.health()
    cfg = auth_config()
    if cfg is not None:
        # public identifiers (they ship in the website too) — lets anyone check the server and the
        # app agree on which Auth0 tenant and API a sign-in token must come from
        report["auth"] = {"issuer": cfg.issuer, "audience": cfg.audience, "linked_logins": len(cfg.personas)}
        from app import auth0_ciba

        ciba = auth0_ciba.config()  # never the secret: only whether push approvals are on, and for how many
        report["auth"]["push_approvals"] = {"on": ciba is not None, "lenders": len(ciba.users) if ciba else 0}
    return report


@app.get("/personas", response_model=list[Persona])
def personas() -> list[Persona]:
    return data.personas()


@app.get("/me", response_model=Me)
def me(user: OptionalUser, persona: str = PERSONA) -> Me:
    persona = persona_for(user, persona)
    try:
        return data.me(persona)
    except data.PersonaNotFound:
        raise HTTPException(404, f"Unknown persona '{persona}'") from None


@app.get("/spending", response_model=Spending)
def spending(
    user: OptionalUser,
    month: str | None = Query(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="YYYY-MM, default this month"),
    persona: str = PERSONA,
) -> Spending:
    persona = persona_for(user, persona)
    month = month or datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m")
    try:
        return data.spending(month, persona)
    except data.PersonaNotFound:
        raise HTTPException(404, f"Unknown persona '{persona}'") from None


# ---------- peer-to-peer ----------
# Real Nessie writes need LIVE_TRANSFERS=1 (off until these routes check the Auth0 user); while off,
# writes return realistic results without persisting, so the app's P2P screens work end to end.
P2P_FAILED = "The payment may be incomplete — we're checking with the bank"


@app.get("/p2p", response_model=P2PSummary)
def p2p(user: OptionalUser, persona: str = PERSONA) -> P2PSummary:
    persona = persona_for(user, persona)
    try:
        return data.p2p_summary(persona)
    except data.PersonaNotFound:
        raise HTTPException(404, f"Unknown persona '{persona}'") from None


@app.post("/p2p/send", response_model=P2PPayment)
def p2p_send(req: P2PSend, user: OptionalUser) -> P2PPayment:
    authorize_money(user, req.persona)
    try:
        return data.p2p_send(req.persona, req.contact_id, req.amount, req.memo)
    except (data.PersonaNotFound, data.ContactNotFound):
        raise HTTPException(404, "Unknown persona or contact") from None
    except data.TransferNotMade as e:
        raise HTTPException(503, "The bank didn't accept the payment — nothing moved, try again") from e
    except Exception as e:
        log.exception("p2p send needs reconciliation")
        raise HTTPException(502, P2P_FAILED) from e


@app.post("/p2p/requests", response_model=P2PRequest)
def p2p_request(req: P2PSend, user: OptionalUser) -> P2PRequest:
    authorize_money(user, req.persona)
    try:
        return data.p2p_request(req.persona, req.contact_id, req.amount, req.memo)
    except (data.PersonaNotFound, data.ContactNotFound):
        raise HTTPException(404, "Unknown persona or contact") from None


@app.post("/p2p/requests/{request_id}/settle", response_model=P2PRequest)
def p2p_settle(request_id: str, user: OptionalUser) -> P2PRequest:
    # settling pays the requester; only they mark it paid until the payer has their own sign-in
    owner = data.p2p_request_owner(request_id)
    if owner is None:
        raise HTTPException(409, "That request isn't open")
    authorize_money(user, owner)
    try:
        return data.p2p_settle(request_id)
    except data.RequestNotOpen:
        raise HTTPException(409, "That request isn't open") from None
    except data.TransferNotMade as e:
        raise HTTPException(503, "The bank didn't accept the payment — nothing moved, try again") from e
    except Exception as e:
        log.exception("p2p settle needs reconciliation")
        raise HTTPException(502, P2P_FAILED) from e


# ---------- family safety net ----------
# The agent covers a family member's forecast dip from someone else's money — automatically under
# the lender's limit, with an Auth0 push approval over it — and repays the lender on payday.
# Only the lender sets their own limits and answers bridges where they are the lender (authorize_money).


def _live_writes() -> bool:
    from app import safety_net

    return safety_net.writes_enabled()


@app.get("/safety-net", response_model=SafetyNetSummary)
def safety_net_summary(user: OptionalUser, persona: str = PERSONA) -> SafetyNetSummary:
    persona = persona_for(user, persona)
    try:
        return safety_views.summary(persona)
    except LookupError:
        raise HTTPException(404, f"Unknown persona '{persona}'") from None


@app.put("/safety-net/limits", response_model=SafetyLimit)
def set_safety_limit(req: SetLimit, user: OptionalUser) -> SafetyLimit:
    authorize_money(user, req.lender)  # only the lender sets their own limit
    if req.lender == req.borrower:
        raise HTTPException(422, "You can't set a limit for yourself")
    names = {p.slug: p.first_name for p in data.personas()}
    if req.lender not in names or req.borrower not in names:
        raise HTTPException(404, "Unknown persona")
    if _live_writes():
        from app.db import pool, safety_repo

        with pool.connection() as conn:
            safety_repo.set_limit(conn, req.lender, req.borrower, req.limit, req.enabled)
            safety_repo.add_event(
                conn, req.borrower, "limit_changed", f"{names[req.lender]} set your safety net to ${req.limit:,.0f}."
            )
            conn.commit()
            return safety_views.limit(safety_repo.limits(conn, lender=req.lender, borrower=req.borrower)[0])
    return SafetyLimit(
        lender=req.lender,
        lender_name=names[req.lender],
        borrower=req.borrower,
        borrower_name=names[req.borrower],
        limit=req.limit,
        outstanding=0,
        remaining=req.limit,
        enabled=req.enabled,
    )


@app.post("/safety-net/run", response_model=list[SafetyDecision])
def run_safety_net(
    user: OptionalUser, persona: str | None = Query(None, pattern=r"^[a-z]{1,32}$")
) -> list[SafetyDecision]:
    """Check for upcoming dips now. With real writes off this is a dry run (executed: false). With them
    on, it acts only on limits lenders already set — and still requires a signed-in caller, who can
    only run it for themselves."""
    if user is not None:
        persona = persona_for(user, persona or "")
    elif data.writes_enabled():
        authorize_money(None, persona)
    if not get_settings().live:
        demo = safety_views.demo_summary("maya").borrowed[0]
        return [
            SafetyDecision(
                borrower="maya",
                action="auto_bridge",
                reason=demo.reason,
                amount=demo.amount,
                lender="sam",
                shortfall_date=demo.shortfall_date,
                low_balance=208.0,
                due_date=demo.due_date,
                executed=False,
                bridge=None,
            )
        ]
    from app import demo, safety_net

    demo.release()  # running it by hand is the live moment: automatic passes resume after it
    return [safety_views.decision(d, b) for d, b in safety_net.run([persona] if persona else None)]


def _bridge_action(bridge_id: str, approve: bool, user: User | None) -> Bridge:
    if not get_settings().live:
        b = next((x for x in safety_views.demo_summary("jordan").approvals_waiting if x.id == bridge_id), None)
        if b is None:
            raise HTTPException(409, "That bridge isn't waiting for approval")
        authorize_money(user, b.lender)
        return b.model_copy(update={"status": "active" if approve else "declined"})
    from app import safety_net
    from app.db import pool, safety_repo

    with pool.connection() as conn:
        lender = (safety_repo.bridge(conn, bridge_id) or {}).get("lender_slug")
    if lender is None:
        raise HTTPException(409, "That bridge isn't waiting for approval")
    authorize_money(user, lender)  # only the bridge's lender answers it
    if not _live_writes():
        with pool.connection() as conn:
            row = safety_repo.bridge(conn, bridge_id)
        if row is None or row["status"] != "pending_approval":
            raise HTTPException(409, "That bridge isn't waiting for approval")
        return safety_views.bridge(row).model_copy(update={"status": "active" if approve else "declined"})
    with pool.connection() as conn:
        current = safety_repo.bridge(conn, bridge_id)
    if approve and current and current["approval_channel"] == "auth0_push":
        # sent to the lender's phone: only the Auth0 push answer (polled in the background) may approve it,
        # so an in-app call can't bypass the lender's own confirmation
        raise HTTPException(409, "This bridge is waiting for approval on the lender's phone")
    row = safety_net.approve(bridge_id) if approve else safety_net.decline(bridge_id)
    if row is None:
        raise HTTPException(409, "That bridge isn't waiting for approval, or the transfer didn't go through")
    return safety_views.bridge(row)


@app.post("/safety-net/bridges/{bridge_id}/approve", response_model=Bridge)
def approve_bridge(bridge_id: str, user: OptionalUser) -> Bridge:
    return _bridge_action(bridge_id, approve=True, user=user)


@app.post("/safety-net/bridges/{bridge_id}/decline", response_model=Bridge)
def decline_bridge(bridge_id: str, user: OptionalUser) -> Bridge:
    return _bridge_action(bridge_id, approve=False, user=user)


@app.post("/safety-net/bridges/{bridge_id}/repay", response_model=Bridge)
def repay_bridge(bridge_id: str, user: OptionalUser) -> Bridge:
    """The borrower pays a bridge back early (a real Nessie move back to the lender). Only the
    borrower can, and never if it would take them under the amount they keep."""
    if not get_settings().live:
        b = next((x for x in safety_views.demo_summary("maya").borrowed if x.id == bridge_id), None)
        if b is None:
            raise HTTPException(409, "That bridge isn't waiting to be paid back.")
        authorize_money(user, b.borrower)
        return b.model_copy(update={"status": "repaid"})
    from app import safety_net
    from app.db import pool, safety_repo

    with pool.connection() as conn:
        borrower = (safety_repo.bridge(conn, bridge_id) or {}).get("borrower_slug")
    if borrower is None:
        raise HTTPException(404, "No such bridge.")
    authorize_money(user, borrower)  # only the borrower pays back
    if not _live_writes():
        raise HTTPException(503, "Real transfers are switched off, so nothing can be paid back right now.")
    try:
        return safety_views.bridge(safety_net.repay_now(bridge_id))
    except safety_net.RepayRefused as e:
        raise HTTPException(409, str(e)) from None


# ---------- demo controls ----------
# A signed-in demo login (Maya, Jordan or Sam) can rebuild the demo and pause automatic bridges, so
# the story can be rehearsed and is fresh for the judges. Only the demo personas are ever touched.


def _demo_user(user: User | None) -> None:
    from app import demo

    if user is None:
        raise HTTPException(
            401, "Sign in with a demo account to reset the demo.", headers={"WWW-Authenticate": "Bearer"}
        )
    if persona_for(user, "") not in demo.DEMO_PERSONAS:
        raise HTTPException(403, "Only the demo accounts can reset the demo.")
    if not get_settings().live:
        raise HTTPException(503, "The demo reset needs the live Nessie connection.")


@app.post("/demo/reset", status_code=202)
def demo_reset(user: OptionalUser) -> dict:
    from app import demo

    _demo_user(user)
    if not demo.start_reset():
        raise HTTPException(409, "A reset is already running.")
    return demo.status()


@app.get("/demo/status")
def demo_status(user: OptionalUser) -> dict:
    from app import demo

    _demo_user(user)
    return demo.status()


@app.get("/forecast", response_model=Forecast)
def forecast(user: OptionalUser, days: int = Query(30, ge=1, le=365), persona: str = PERSONA) -> Forecast:
    return engine.forecast(days=days, persona=persona_for(user, persona))  # days bounded: cost is linear


@app.post("/simulate", response_model=Forecast)
def simulate(req: SimulateRequest, user: OptionalUser, persona: str = PERSONA) -> Forecast:
    return engine.simulate_purchase(req.amount, req.date, req.label, persona=persona_for(user, persona))


@app.get("/recurring", response_model=list[Recurring])
def recurring(user: OptionalUser, persona: str = PERSONA) -> list[Recurring]:
    return engine.recurring(persona=persona_for(user, persona))


@app.post("/agent/chat", response_model=ChatResponse)
def agent_chat(req: ChatRequest, user: OptionalUser) -> ChatResponse:
    return agent.chat(req.message, persona=persona_for(user, req.persona))


_approve_lock = threading.Lock()  # routes run in a thread pool: make check-and-claim atomic


@app.post("/actions/{action_id}/approve", response_model=PendingAction)
def approve(action_id: str, user: OptionalUser) -> PendingAction:
    if action_id in agent.PENDING:  # an unknown id still gets its 404 below
        authorize_money(user, agent.persona_of(action_id))  # only the person it was proposed for
    with _approve_lock:
        action = agent.PENDING.get(action_id)
        if action is None:
            raise HTTPException(404, "No such pending action")
        if action.status != "awaiting_approval":
            raise HTTPException(409, "Action already processed")  # one approval = one transfer, never a replay
        if action.kind != "transfer" or not action.amount or action.amount <= 0:
            raise HTTPException(422, "Only positive transfers can be approved right now")
        action.status = "approved"  # claimed: a concurrent approve now gets 409
    try:
        # the persona the agent proposed this for — never the default (that would move Maya's money for Jordan)
        data.move_savings_to_checking(action.amount, action.description, agent.persona_of(action_id))
    except data.TransferNotMade as e:
        action.status = "awaiting_approval"  # nothing moved, so a retry is safe
        log.warning("transfer not made: %s", e)
        raise HTTPException(503, "The bank didn't accept the transfer — nothing moved, try again") from e
    except Exception as e:
        action.status = "failed"  # outcome unknown: never let it be approved twice
        log.exception("transfer needs reconciliation")
        raise HTTPException(502, "The transfer may be incomplete — we're checking with the bank") from e
    action.status = "executed"
    return action

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


def background_pass() -> None:
    """Every interval: pull Nessie into Tiger Data, then let the safety net act (repayments,
    push approvals, new bridges) — the last part only when real writes are on."""
    sync_personas(prepare=False)
    from app import safety_net

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
app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_methods=["GET", "POST"], allow_headers=["*"])


@app.get("/health")
def health() -> dict:
    return data.health()


@app.get("/personas", response_model=list[Persona])
def personas() -> list[Persona]:
    return data.personas()


@app.get("/me", response_model=Me)
def me(persona: str = PERSONA) -> Me:
    try:
        return data.me(persona)
    except data.PersonaNotFound:
        raise HTTPException(404, f"Unknown persona '{persona}'") from None


@app.get("/spending", response_model=Spending)
def spending(
    month: str | None = Query(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="YYYY-MM, default this month"),
    persona: str = PERSONA,
) -> Spending:
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
def p2p(persona: str = PERSONA) -> P2PSummary:
    try:
        return data.p2p_summary(persona)
    except data.PersonaNotFound:
        raise HTTPException(404, f"Unknown persona '{persona}'") from None


@app.post("/p2p/send", response_model=P2PPayment)
def p2p_send(req: P2PSend) -> P2PPayment:
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
def p2p_request(req: P2PSend) -> P2PRequest:
    try:
        return data.p2p_request(req.persona, req.contact_id, req.amount, req.memo)
    except (data.PersonaNotFound, data.ContactNotFound):
        raise HTTPException(404, "Unknown persona or contact") from None


@app.post("/p2p/requests/{request_id}/settle", response_model=P2PRequest)
def p2p_settle(request_id: str) -> P2PRequest:
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
# TODO(auth): limits may only be set by the logged-in lender; approve/decline only by the bridge's lender.


def _live_writes() -> bool:
    from app import safety_net

    return safety_net.writes_enabled()


@app.get("/safety-net", response_model=SafetyNetSummary)
def safety_net_summary(persona: str = PERSONA) -> SafetyNetSummary:
    try:
        return safety_views.summary(persona)
    except LookupError:
        raise HTTPException(404, f"Unknown persona '{persona}'") from None


@app.put("/safety-net/limits", response_model=SafetyLimit)
def set_safety_limit(req: SetLimit) -> SafetyLimit:
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
def run_safety_net(persona: str | None = Query(None, pattern=r"^[a-z]{1,32}$")) -> list[SafetyDecision]:
    """Check for upcoming dips now. With real writes off this is a dry run (executed: false)."""
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
    from app import safety_net

    return [safety_views.decision(d, b) for d, b in safety_net.run([persona] if persona else None)]


def _bridge_action(bridge_id: str, approve: bool) -> Bridge:
    if not get_settings().live:
        b = next((x for x in safety_views.demo_summary("jordan").approvals_waiting if x.id == bridge_id), None)
        if b is None:
            raise HTTPException(409, "That bridge isn't waiting for approval")
        return b.model_copy(update={"status": "active" if approve else "declined"})
    from app import safety_net
    from app.db import pool, safety_repo

    if not _live_writes():
        with pool.connection() as conn:
            row = safety_repo.bridge(conn, bridge_id)
        if row is None or row["status"] != "pending_approval":
            raise HTTPException(409, "That bridge isn't waiting for approval")
        return safety_views.bridge(row).model_copy(update={"status": "active" if approve else "declined"})
    row = safety_net.approve(bridge_id) if approve else safety_net.decline(bridge_id)
    if row is None:
        raise HTTPException(409, "That bridge isn't waiting for approval, or the transfer didn't go through")
    return safety_views.bridge(row)


@app.post("/safety-net/bridges/{bridge_id}/approve", response_model=Bridge)
def approve_bridge(bridge_id: str) -> Bridge:
    return _bridge_action(bridge_id, approve=True)


@app.post("/safety-net/bridges/{bridge_id}/decline", response_model=Bridge)
def decline_bridge(bridge_id: str) -> Bridge:
    return _bridge_action(bridge_id, approve=False)


@app.get("/forecast", response_model=Forecast)
def forecast(days: int = Query(30, ge=1, le=365)) -> Forecast:  # bounded: cost is linear in days
    return engine.forecast(days=days)


@app.post("/simulate", response_model=Forecast)
def simulate(req: SimulateRequest) -> Forecast:
    return engine.simulate_purchase(req.amount, req.date, req.label)


@app.get("/recurring", response_model=list[Recurring])
def recurring() -> list[Recurring]:
    return engine.recurring()


@app.post("/agent/chat", response_model=ChatResponse)
def agent_chat(req: ChatRequest) -> ChatResponse:
    return agent.chat(req.message)


_approve_lock = threading.Lock()  # routes run in a thread pool: make check-and-claim atomic


@app.post("/actions/{action_id}/approve", response_model=PendingAction)
def approve(action_id: str) -> PendingAction:
    # TODO(auth): require the Auth0 user (Depends) and check action.owner_id == user.id before
    # anything else, and take the persona from the user. Only then set LIVE_TRANSFERS=1 —
    # until that flag is on, approving never writes to Nessie (see data.move_savings_to_checking).
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
        data.move_savings_to_checking(action.amount, action.description)
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

"""Six Seven Bucks Left API — owner: rshah2001. Routes are thin: each one delegates to the module its owner maintains.

Run:  uvicorn app.main:app --reload --port 8000   (docs at http://localhost:8000/docs)
"""

import asyncio
import contextlib
import functools
import logging
import os
import threading
from contextlib import asynccontextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from app import data
from app.agent import chat as agent
from app.config import get_settings
from app.db import pool
from app.db import schema as db_schema
from app.forecast import engine
from app.ingest import sync_personas
from app.schemas import (
    ChatRequest,
    ChatResponse,
    Forecast,
    Me,
    PendingAction,
    Persona,
    Recurring,
    SimulateRequest,
    Spending,
)
from app.sync_loop import run_periodically

log = logging.getLogger("runway")
PERSONA = Query(data.DEFAULT_PERSONA, pattern=r"^[a-z]{1,32}$", description="demo persona slug, e.g. maya")


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
            job = functools.partial(sync_personas, prepare=False)
            sync_task = asyncio.create_task(run_periodically(job, settings.sync_interval, initial_delay=15))
    yield
    if sync_task:
        sync_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sync_task
    pool.close()


app = FastAPI(title="Six Seven Bucks Left API", lifespan=lifespan)

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

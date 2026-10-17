"""Runway API — owner: rshah2001. Routes are thin: each one delegates to the module its owner maintains.

Run:  uvicorn app.main:app --reload --port 8000   (docs at http://localhost:8000/docs)
"""

import os

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from app.agent import chat as agent
from app.forecast import engine
from app.nessie import client as nessie
from app.schemas import ChatRequest, ChatResponse, Forecast, Me, PendingAction, Recurring, SimulateRequest

app = FastAPI(title="Runway API")

# only the app's own origins may call the API; set CORS_ORIGINS (comma-separated) when deploying
ALLOWED_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:8081,http://localhost:19006").split(",")
app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_methods=["GET", "POST"], allow_headers=["*"])


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/me", response_model=Me)
def me() -> Me:
    return nessie.get_me()


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


@app.post("/actions/{action_id}/approve", response_model=PendingAction)
def approve(action_id: str) -> PendingAction:
    # TODO(auth): require the Auth0 user (Depends) and check action.owner_id == user.id before
    # anything else. Until then this only moves money between the mock demo accounts.
    action = agent.PENDING.get(action_id)
    if action is None:
        raise HTTPException(404, "No such pending action")
    if action.status != "awaiting_approval":
        raise HTTPException(409, "Action already processed")  # one approval = one transfer, never a replay
    action.status = "approved"
    nessie.create_transfer("demo-sav", "demo-chk", action.amount or 0, action.description)
    action.status = "executed"
    return action

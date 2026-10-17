"""Runway API. Routes are thin: each one delegates to the module its owner maintains.

Run:  uvicorn app.main:app --reload --port 8000   (docs at http://localhost:8000/docs)
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.agent import chat as agent
from app.forecast import engine
from app.nessie import client as nessie
from app.schemas import ChatRequest, ChatResponse, Forecast, Me, PendingAction, Recurring, SimulateRequest

app = FastAPI(title="Runway API")

# the Expo dev server (web) runs on a different port; tighten this before deploying
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/me", response_model=Me)
def me() -> Me:
    return nessie.get_me()


@app.get("/forecast", response_model=Forecast)
def forecast(days: int = 30) -> Forecast:
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
    # owner C: gate this behind Auth0 approval before calling Nessie
    action = agent.PENDING.get(action_id)
    if action is None:
        raise HTTPException(404, "No such pending action")
    nessie.create_transfer("demo-sav", "demo-chk", action.amount or 0, action.description)
    action.status = "executed"
    return action

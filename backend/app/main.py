"""Runway API — owner: rshah2001. Routes are thin: each one delegates to the module its owner maintains.

Run:  uvicorn app.main:app --reload --port 8000   (docs at http://localhost:8000/docs)
"""

import asyncio
import contextlib
import logging
import os
import re
import threading
from contextlib import asynccontextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from app import data, forecast_history, safety_views, spending_compare
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
    ActivityItem,
    AgreementChange,
    Bridge,
    ChatRequest,
    ChatResponse,
    CirclePerson,
    CircleView,
    Forecast,
    Me,
    NewCircle,
    P2PPayment,
    P2PRequest,
    P2PSend,
    P2PSummary,
    PendingAction,
    Persona,
    PushStatus,
    PushSubscription,
    Recurring,
    SafetyDecision,
    SafetyLimit,
    SafetyNetSummary,
    Scenarios,
    SetExposure,
    SetLimit,
    SetPreferences,
    SetReceiving,
    SetSafeFloor,
    SetSupportMode,
    SimulateRequest,
    Spending,
    SupportSummary,
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
    """Every interval: pull Nessie into Tiger Data, save today's forecasts and score past ones (once a
    day per persona), then let the safety net act (repayments, push approvals, new bridges) — the last
    part only when real writes are on."""
    sync_personas(prepare=False)
    try:
        forecast_history.run()
    except Exception:  # the track record is informational: it must never hold up the safety net
        log.exception("forecast history pass failed")
    from app import alerts, demo, safety_net

    alerts.run()  # heads-ups don't move money, so they go out even while a demo reset holds bridges
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
    from app import prefs

    persona = persona_for(user, persona)
    try:
        base = data.me(persona)
    except data.PersonaNotFound:
        raise HTTPException(404, f"Unknown persona '{persona}'") from None
    return base.model_copy(
        update={
            "safe_floor": prefs.floor(persona),
            "alerts_only": prefs.setting(persona, "alerts_only"),
            "family_cover": prefs.setting(persona, "family_cover"),
            "discreet_notifications": prefs.setting(persona, "discreet_notifications"),
        }
    )


def _own_settings(user: User | None, requested: str) -> str:
    """Whose settings a change applies to: always your own. Signed in, the request's persona is
    ignored; with sign-in configured, an anonymous caller gets 401. These settings decide when family
    money moves, so they follow the money rule: with real transfers on, an anonymous caller never
    changes them."""
    if user is not None:
        return persona_for(user, "")
    if auth_config() is not None:
        raise HTTPException(401, "Sign in to change this.", headers={"WWW-Authenticate": "Bearer"})
    # sign-in off (CI, offline demo): only the listed demo people
    if requested not in {p.slug for p in data.personas()}:  # nothing is saved for someone who doesn't exist
        raise HTTPException(404, f"Unknown persona '{requested}'")
    authorize_money(None, requested)
    return requested


@app.put("/me/safe-floor", response_model=Me)
def set_safe_floor(req: SetSafeFloor, user: OptionalUser) -> Me:
    """Set how much you keep in checking (only for yourself)."""
    from app import prefs

    persona = _own_settings(user, req.persona)
    try:
        prefs.set_floor(persona, req.amount)
    except prefs.FloorOutOfRange as e:
        raise HTTPException(422, str(e)) from None
    return me(user, persona)


@app.put("/me/preferences", response_model=Me)
def set_preferences(req: SetPreferences, user: OptionalUser) -> Me:
    """Turn alerts-only or family cover on or off (only for yourself)."""
    from app import prefs

    persona = _own_settings(user, req.persona)
    for name in ("alerts_only", "family_cover", "discreet_notifications"):
        value = getattr(req, name)
        if value is not None:
            prefs.set_setting(persona, name, value)
    if req.family_cover is False and get_settings().live:
        from app import safety_net

        safety_net.withdraw_requests(persona)  # nobody stays asked on your behalf
    return me(user, persona)


# ---------- heads-up alerts (app/alerts.py) ----------
@app.get("/alerts/key", response_model=PushStatus)
def alerts_key() -> PushStatus:
    """The public key a browser subscribes with (public by design); None when alerts are off."""
    from app import alerts

    keys = alerts.vapid()
    return PushStatus(key=keys.public_key if keys else None)


@app.put("/me/push", response_model=PushStatus)
def push_subscribe(req: PushSubscription, user: OptionalUser) -> PushStatus:
    """This browser wants your heads-ups (only for yourself)."""
    from app import alerts

    keys = alerts.vapid()
    if keys is None:
        raise HTTPException(503, "Alerts to your phone aren't set up on this server yet.")
    persona = _own_settings(user, req.persona)
    try:
        alerts.subscribe(persona, req.endpoint, req.p256dh, req.auth)
    except ValueError:
        raise HTTPException(422, "That isn't a browser push address.") from None
    return PushStatus(key=keys.public_key)


@app.post("/me/push/test", response_model=PushStatus)
def push_test(user: OptionalUser, persona: str = PERSONA) -> PushStatus:
    """Send yourself your current status now, to check alerts reach this phone."""
    from app import alerts
    from app.cashflow import LOCAL_TZ

    keys = alerts.vapid()
    if keys is None:
        raise HTTPException(503, "Alerts to your phone aren't set up on this server yet.")
    persona = _own_settings(user, persona)
    return PushStatus(key=keys.public_key, sent=alerts.test(persona, datetime.now(LOCAL_TZ).date()))


@app.get("/spending", response_model=Spending)
def spending(
    user: OptionalUser,
    month: str | None = Query(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="YYYY-MM, default this month"),
    persona: str = PERSONA,
) -> Spending:
    persona = persona_for(user, persona)
    today = datetime.now(ZoneInfo("America/New_York")).date()
    month = month or today.strftime("%Y-%m")
    try:
        this = data.spending(month, persona)
    except data.PersonaNotFound:
        raise HTTPException(404, f"Unknown persona '{persona}'") from None
    year, mon = map(int, month.split("-"))
    previous = f"{year - (mon == 1)}-{(mon - 2) % 12 + 1:02d}"
    try:  # informational: a failed read of last month never breaks this month's screen
        last = data.spending(previous, persona)
    except Exception:
        log.exception("spending: couldn't read %s for the comparison", previous)
        return this
    # a month in progress is compared with the same days of the last one; a finished month, whole
    through = today.day if month == today.strftime("%Y-%m") else None
    return this.model_copy(update={"compare": spending_compare.compare(this, last, through_day=through)})


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
        return data.p2p_send(req.persona, req.contact_id, req.amount, req.memo, req.client_key)
    except (data.PersonaNotFound, data.ContactNotFound):
        raise HTTPException(404, "Unknown persona or contact") from None
    except data.PaymentInProgress:
        raise HTTPException(409, "That payment is already being sent") from None
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


# ---------- Quiet Support Agreements: consent, from each person's own side ----------
@app.get("/support", response_model=SupportSummary)
def support_summary(user: OptionalUser, persona: str = PERSONA) -> SupportSummary:
    """My agreements — as supporter and as recipient. No one's balance, income or spending, ever."""
    return safety_views.support_for(persona_for(user, persona))


def _change_agreement(req: AgreementChange, user: User | None, action: str) -> SupportSummary:
    actor = _own_settings(user, req.persona)  # you only ever act for yourself
    if actor not in (req.supporter, req.recipient) or req.supporter == req.recipient:
        raise HTTPException(403, "You can only change your own side of an agreement")
    names = {p.slug for p in data.personas()}
    if req.supporter not in names or req.recipient not in names:
        raise HTTPException(404, "Unknown persona")
    if not get_settings().live:
        return safety_views.demo_support(actor)
    from app import agreements
    from app.db import agreements_repo, pool, safety_repo

    with pool.connection() as conn:
        safety_repo.lock_people(conn, req.supporter, req.recipient)  # same locks as money decisions
        if action == "consent":
            agreements.consent(conn, actor, req.supporter, req.recipient)
        else:
            agreements.revoke(conn, actor, req.supporter, req.recipient)
            if actor == req.recipient:  # nobody is left being asked on the recipient's behalf
                for b in safety_repo.pending_approvals(conn, lender=req.supporter):
                    if b["borrower_slug"] == req.recipient:
                        safety_repo.transition(conn, b["id"], ("pending_approval",), "declined")
        conn.commit()
        return safety_views.support_summary(actor, agreements_repo.involving(conn, actor))


# ---------- named circles (membership only — never money; app/circles.py) ----------
@app.get("/circles", response_model=list[CircleView])
def circles_mine(user: OptionalUser, persona: str = PERSONA) -> list[CircleView]:
    return safety_views.circles_for(persona_for(user, persona))


def _circle_act(user: User | None, persona: str, act) -> list[CircleView]:
    actor = _own_settings(user, persona)
    if not get_settings().live:
        return safety_views.circles_for(actor)
    from app import circles
    from app.db import pool

    with pool.connection() as conn:
        try:
            act(circles, conn, actor)
        except circles.CircleRefused as e:
            raise HTTPException(403, str(e)) from None
        conn.commit()
    return safety_views.circles_for(actor)


@app.post("/circles", response_model=list[CircleView])
def circle_create(req: NewCircle, user: OptionalUser) -> list[CircleView]:
    return _circle_act(user, req.persona, lambda c, conn, me: c.create(conn, me, req.name))


@app.post("/circles/{circle_id}/{action}", response_model=list[CircleView])
def circle_change(circle_id: str, action: str, req: CirclePerson, user: OptionalUser) -> list[CircleView]:
    """invite / remove (need `slug`), accept / decline / leave (your own membership)."""
    if not re.fullmatch(r"circle-[a-z0-9-]{1,40}", circle_id):
        raise HTTPException(404, "Unknown circle")
    known = {p.slug for p in data.personas()}
    if action in ("invite", "remove") and req.slug not in known:
        raise HTTPException(404, "Unknown person")
    acts = {
        "invite": lambda c, conn, me: c.invite(conn, me, circle_id, req.slug),
        "remove": lambda c, conn, me: c.remove(conn, me, circle_id, req.slug),
        "accept": lambda c, conn, me: c.answer(conn, me, circle_id, True),
        "decline": lambda c, conn, me: c.answer(conn, me, circle_id, False),
        "leave": lambda c, conn, me: c.leave(conn, me, circle_id),
    }
    if action not in acts:
        raise HTTPException(404, "Unknown action")
    return _circle_act(user, req.persona, acts[action])


@app.get("/forecast/scenarios", response_model=Scenarios)
def forecast_scenarios(user: OptionalUser, persona: str = PERSONA) -> Scenarios:
    """Time Machine: your own forecast with no help, one supporter, your circle, and the unsafe version
    Runway blocks — for the Today chart. Only your own money, and amounts you can already see."""
    from app import scenarios

    return scenarios.build(scenarios.inputs_for(persona_for(user, persona)))


@app.get("/activity", response_model=list[ActivityItem])
def activity_feed(user: OptionalUser, persona: str = PERSONA) -> list[ActivityItem]:
    """My support received, provided and repaid — each with a why, from my side only."""
    return safety_views.activity_for(persona_for(user, persona))


@app.put("/support/mode", response_model=SupportSummary)
def support_mode(req: SetSupportMode, user: OptionalUser) -> SupportSummary:
    """The supporter chooses: Runway may move up to my limit ('auto'), or ask me every time ('approval')."""
    actor = _own_settings(user, req.persona)
    if req.recipient not in {p.slug for p in data.personas()} or req.recipient == actor:
        raise HTTPException(404, "Unknown persona")
    if not get_settings().live:
        return safety_views.demo_support(actor)
    from app import agreements
    from app.db import pool, safety_repo

    with pool.connection() as conn:
        safety_repo.lock_people(conn, actor, req.recipient)  # same locks as money decisions
        try:
            agreements.set_mode(conn, actor, actor, req.recipient, req.mode)
        except agreements.NotYourAgreement:
            raise HTTPException(403, "Only the supporter chooses how their support works") from None
        conn.commit()
    return safety_views.support_for(actor)


@app.put("/support/receiving", response_model=SupportSummary)
def support_receiving(req: SetReceiving, user: OptionalUser) -> SupportSummary:
    """My limits as a recipient: the most I'll owe at once, and whether several people may help together."""
    actor = _own_settings(user, req.persona)
    if not get_settings().live:
        return safety_views.demo_support(actor).model_copy(
            update={"max_owed": req.max_owed, "allow_multi": req.allow_multi}
        )
    from app.db import pool, repo, safety_repo

    with pool.connection() as conn:
        safety_repo.lock_people(conn, actor)
        repo.set_receiving(conn, actor, None if req.max_owed is None else round(req.max_owed, 2), req.allow_multi)
        conn.commit()
    return safety_views.support_for(actor)


@app.put("/support/exposure", response_model=SupportSummary)
def support_exposure(req: SetExposure, user: OptionalUser) -> SupportSummary:
    """The most I let Runway have out across everyone I support. Money already out still counts."""
    actor = _own_settings(user, req.persona)
    if not get_settings().live:
        return safety_views.demo_support(actor).model_copy(update={"exposure_limit": req.limit})
    from app.db import pool, repo, safety_repo

    with pool.connection() as conn:
        safety_repo.lock_people(conn, actor)
        repo.set_exposure_limit(conn, actor, round(req.limit, 2))
        conn.commit()
    return safety_views.support_for(actor)


@app.post("/support/consent", response_model=SupportSummary)
def support_consent(req: AgreementChange, user: OptionalUser) -> SupportSummary:
    """Say yes to your own side: as supporter ("Runway may cover them, within my limit") or as
    recipient ("Runway may ask them to cover me"). Automatic help needs both."""
    return _change_agreement(req, user, "consent")


@app.post("/support/revoke", response_model=SupportSummary)
def support_revoke(req: AgreementChange, user: OptionalUser) -> SupportSummary:
    """Either person withdraws. New help stops; money already out still comes back on payday."""
    return _change_agreement(req, user, "revoke")


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
            from app import agreements

            safety_repo.lock_people(conn, req.lender, req.borrower)
            safety_repo.set_limit(conn, req.lender, req.borrower, req.limit, req.enabled)
            agreements.limit_changed(conn, req.lender, req.borrower, req.limit, req.enabled)
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
    # signed out: only the one demo persona asked about — never everyone, which would report each
    # person's low balance to an anonymous visitor
    persona = persona or data.DEFAULT_PERSONA
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
    return [safety_views.decision(d, b) for d, b in safety_net.run([persona])]


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
        return safety_views.for_lender(safety_views.bridge(row)).model_copy(
            update={"status": "active" if approve else "declined"}
        )
    with pool.connection() as conn:
        current = safety_repo.bridge(conn, bridge_id)
    if approve and current and current["approval_channel"] == "auth0_push":
        # sent to the lender's phone: only the Auth0 push answer (polled in the background) may approve it,
        # so an in-app call can't bypass the lender's own confirmation
        raise HTTPException(409, "This bridge is waiting for approval on the lender's phone")
    row = safety_net.approve(bridge_id) if approve else safety_net.decline(bridge_id)
    if row is None:
        raise HTTPException(409, "That bridge isn't waiting for approval, or the transfer didn't go through")
    return safety_views.for_lender(safety_views.bridge(row))  # only the lender answers a bridge


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
APPROVABLE_KINDS = ("transfer", "p2p_request")


def _execute(action_id: str, action: PendingAction) -> None:
    """Carry out an approved action through the same data function its own route uses."""
    # the persona the agent proposed this for — never the default (that would move Maya's money for Jordan)
    persona = agent.persona_of(action_id)
    if action.kind == "p2p_request":
        contact_id, memo = agent.p2p_details(action_id) or ("", "")
        data.p2p_request(persona, contact_id, action.amount or 0, memo)  # as POST /p2p/requests: nothing moves
        return
    data.move_savings_to_checking(action.amount or 0, action.description, persona)


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
        if action.kind not in APPROVABLE_KINDS or not action.amount or action.amount <= 0:
            raise HTTPException(422, "Only positive transfers and requests can be approved right now")
        action.status = "approved"  # claimed: a concurrent approve now gets 409
    try:
        _execute(action_id, action)
    except (data.PersonaNotFound, data.ContactNotFound) as e:
        action.status = "failed"  # the contact or persona is gone: retrying can't help
        raise HTTPException(404, "Unknown persona or contact") from e
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

# Family safety net

> **An AI that acts on your behalf so you never have to ask for money.**
> Each family member sets how much the agent may move from *them* to someone else without asking —
> as long as it comes back by that person's next payday. Under the limit it just happens; over it,
> the lender gets an Auth0 push on their phone. On payday the lender is repaid automatically and
> sees *"💸 You got your $100 back from Maya."*

## How it decides (`backend/app/safety_net.py` → `decide()`, pure + unit-tested)

1. **Spot the dip.** Project the borrower's checking balance to their next payday
   (`app/cashflow.py`: live balance − bills − typical daily debit spending + paydays ± scheduled
   repayments). If it drops under the **$300 safety floor**, the gap is rounded up to whole tens
   (a $92 gap → a $100 bridge).
2. **Find a safe helper.** Among family members with a limit for the borrower, keep only those whose
   *own* projection stays above $300 after lending. Pick the one with the most runway.
3. **Act.** Fits in what's left of their limit → **automatic** bridge (real Nessie money: transfer on
   the lender + deposit on the borrower). Doesn't fit → **approval**: Auth0 push (in-app fallback).
4. **Repay on payday.** On the due date the borrower pays the lender back — but only once the
   paycheck has landed; if repaying would push them under $300 it waits.

## Guardrails

| Rule | Where |
|---|---|
| Only the **lender** sets or raises their limit (never the borrower, never the AI) | `PUT /safety-net/limits` — TODO(auth): must be the logged-in lender |
| Must come back **by the borrower's next payday**, within 31 days | `decide()` → `no_payday` |
| Helping must keep the **helper** above the floor | `decide()` |
| Repaying on payday must keep the **borrower** above the floor, or no bridge | `decide()` |
| The limit counts **everything outstanding**, not each bridge | `safety_limits` + outstanding sum |
| **One bridge at a time** per borrower; someone who owes money never lends (no chains) | `decide()` |
| A **late** repayment freezes new bridges (`repay_failed`) and tells both people | `repay_due()` |
| Covers **forecast gaps from bills and normal spending** — not a one-off purchase you're considering | only the cash-flow projection triggers it |
| Never funds or repays **twice**: every money move first claims the bridge with an atomic status update | `safety_repo.transition()` |
| Every move appears in **both** people's feed | `safety_events` |
| Real money only with `LIVE_TRANSFERS=1` (off until the routes check the Auth0 user) | otherwise `/safety-net/run` is a dry run |

## API

| Method | Path | |
|---|---|---|
| GET | `/safety-net?persona=` | everything one person's screen needs (limits both ways, bridges lent / borrowed with due + repaid dates, approvals waiting, feed, projected low) |
| PUT | `/safety-net/limits` `{lender, borrower, limit, enabled}` | the lender sets their auto limit ($0–$1,000) |
| POST | `/safety-net/run?persona=` | check now (the server also runs it every 5 min); dry run while real transfers are off |
| POST | `/safety-net/bridges/{id}/approve` · `/decline` | the lender answers an over-limit bridge |

## Demo data

Default limits (set by the lenders): **Sam → Maya $100**, **Sam → Jordan $300**, **Jordan → Maya $50**.
Maya's seeded balance is tuned so her lowest point before payday is always **$208** → a **$100
bridge, exactly Sam's limit** (`demo_low_before_payday` in `seed/personas.py`; stable on every day —
tested). For the over-limit moment, lower Sam's limit to $50 live, then run.

## Auth0 push (CIBA) setup — Patil-Hemangi

The backend client is done (`backend/app/auth0_ciba.py`, tested against a fake Auth0). It turns on
when these are configured. **Check the current Auth0 docs for each step** — names move around:

1. **Users**: create an Auth0 user for each lender (Sam, Jordan) and note their user ids (`auth0|…`).
2. **Push MFA**: enable *Push notifications via Auth0 Guardian*; each lender installs **Auth0
   Guardian** on their phone and enrolls (log in once and follow the enrollment prompt).
3. **CIBA client**: create a *Regular Web Application* ("Runway Agent"), enable the **Client-Initiated
   Backchannel Authentication (CIBA)** grant type, copy its client id + secret. Make sure CIBA is
   enabled for the tenant (Auth0 for AI Agents → asynchronous authorization).
4. **Server env** (`/opt/runway/.env`): `AUTH0_CIBA_CLIENT_ID`, `AUTH0_CIBA_CLIENT_SECRET`,
   `AUTH0_CIBA_USERS=sam=auth0|…,jordan=auth0|…` — then redeploy. Over-limit bridges then push to the
   lender's phone ("Approve 100 for Maya back Oct 23"); the background job polls Auth0 for the answer.

Until then, over-limit bridges show an **in-app** approval card (`approval_channel: "in_app"`).

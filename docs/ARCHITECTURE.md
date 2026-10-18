# Architecture

```
Expo app — web/iOS/Android (Auth0) ──► FastAPI backend (on Vultr)
                                     ├── Nessie client (read + write)
                                     ├── Ingest job ──► Tiger Data (Postgres + TimescaleDB)
                                     │                   ├── transactions + forecast_snapshots hypertables
                                     │                   └── continuous aggregates (daily spend, forecast accuracy)
                                     ├── Forecast engine (deterministic + ML)
                                     └── Gemini agent
                                          tools: get_forecast, simulate_purchase, find_recurring,
                                                 propose_transfer, reschedule_bill
                                                    │
                                                    ▼
                                          Auth0 async approval ──► Nessie POST/PUT
```

## Flow of a "Fix it" request

1. Frontend sends the chat message to `POST /agent/chat`.
2. Gemini picks a tool. Read tools (`get_forecast`, `simulate_purchase`) run immediately.
3. Write tools (`propose_transfer`, `reschedule_bill`) **never execute directly** — they create a
   pending action and trigger an Auth0 approval request to the user's device.
4. On approval, the backend calls Nessie, re-ingests, recomputes the forecast, and the frontend refreshes.

## API contract (implemented as mocks — `backend/app/schemas.py` ↔ `app/src/lib/types.ts`; change only by PR)

| Method | Path | Returns |
|---|---|---|
| GET | `/me?persona=maya` | customer + accounts with live balances (later: from the Auth0 user) |
| GET | `/forecast?days=30` | `{ points: [{date, balance}], low: {date, balance}, events: [...] }` |
| POST | `/simulate` `{amount, date, label}` | same shape as `/forecast`, with the purchase applied |
| GET | `/recurring` | `[{merchant, amount, interval_days, next_date}]` |
| GET | `/personas` | demo personas (`maya`, `jordan`, `sam`) |
| GET | `/spending?month=YYYY-MM&persona=maya` | category totals, daily spend (continuous aggregate), transactions |
| GET | `/p2p?persona=maya` | contacts (with what they owe you), P2P payment history, requests |
| POST | `/p2p/send` `{persona, contact_id, amount, memo}` | pay a contact — real Nessie transfer + deposit on both sides |
| POST | `/p2p/requests` `{persona, contact_id, amount, memo}` | ask a contact for money (no money moves) |
| POST | `/p2p/requests/{id}/settle` | the contact pays: real money in; atomic, can't be settled twice |
| POST | `/agent/chat` `{message}` | `{reply, tool_calls, pending_action?}` |
| POST | `/agent/fix` `{persona}` | the Fix it button: the savings transfer that covers the dip, as an approval card (no AI, no AI permission needed) |
| POST | `/actions/{id}/approve` | carries out what Ask Runway proposed (a transfer, a request, sending, paying back, a circle change), once |
| POST | `/safety-net/bridges/{id}/repay` `{amount?}` | pay a bridge back early: all of it, or part (the rest goes back on payday) |
| PUT | `/me/preferences` `{alerts_only?, family_cover?, ai_actions?}` | your own on/off settings: Today in calm "alerts only" view; family cover off (no relative's money moves to you); let Ask Runway set things up (each one still approved by you) |
| GET | `/alerts/key` | the Web Push public key (`null` = phone alerts off on this server) |
| PUT | `/me/push` `{endpoint, p256dh, auth}` | this browser gets your heads-ups (only browser push services accepted) |
| POST | `/me/push/test` | sends you your current status now, to check alerts reach the phone |

## Tiger Data schema (live — source of truth: `backend/app/db/schema.py`)

| Object | Kind | Purpose |
|---|---|---|
| `transactions` | **hypertable** (7-day chunks, compressed after 180 days, segmented by customer) | every purchase, deposit, transfer and paid bill — signed amounts |
| `daily_spend` | **continuous aggregate** (real-time, refreshed every 15 min) | per-day, per-category spend → Spending screen + forecast |
| `forecast_snapshots` | **hypertable** (by `made_on`, 30-day chunks, compressed after 90 days, kept 400 days) | every day's forecast as the app showed it, next 30 days, with its band — later scored against the real balance |
| `forecast_accuracy_daily` | **continuous aggregate** (real-time, refreshed hourly) | per persona, per day, for 1/7/14 days ahead: scored days, summed $ error, days inside the band → the report card |
| `accounts` | table | opening balance + time; live balance = opening + transactions since |
| `bills` | table | upcoming recurring bills — the forecast's scheduled outflows |
| `personas`, `merchants` | tables | demo persona ids (+ age), merchant categories |
| `contacts`, `p2p_payments`, `p2p_requests` | tables | peer-to-peer: each contact is a real Nessie customer; every payment keeps both Nessie record ids |
| `money_preferences` | table | per person: what they keep in checking, alerts-only, family cover (NULL = default) |
| `push_subscriptions`, `alerts_sent` | tables | heads-up alerts: which browsers get them, and one row per dip already announced (never twice) |

**For the forecast engine and agent** (`backend/app/db/repo.py` — no SQL needed):
`accounts_with_balances(conn, customer_id)`, `transactions(conn, customer_id, since, until)`,
`bills(conn, customer_id)`, `daily_spend(conn, customer_id, start, end)`; get a connection with
`with pool.connection() as conn:` and the customer with `repo.persona(conn, "maya")`.

### The forecast's track record (Tiger Data)

A **hypertable** is a Postgres table that TimescaleDB splits into time chunks behind the scenes: a
query for "this persona, these days" only opens the chunks for those days, old chunks are compressed
into a columnstore, and expired ones are dropped whole by a retention policy instead of row by row.
A **continuous aggregate** is a materialized `GROUP BY time_bucket(...)` view that TimescaleDB keeps
up to date incrementally: a refresh policy recomputes only the buckets whose rows changed, and
real-time mode adds the newest, not-yet-materialized rows at query time.

Runway uses both to keep itself honest about its forecasts:

1. **Save.** Once a day per persona, the background pass (`app/forecast_history.py`, after the Nessie
   sync) saves the forecast `GET /forecast` shows — same engine, same 30-day horizon, with its p5–p90
   band and the engine version — into `forecast_snapshots`, one row per day ahead. The first forecast
   of the day wins (`ON CONFLICT DO NOTHING`): a later one would already know part of the day.
2. **Score.** Each day it works out the real end-of-day checking balance for the last 35 days (from
   the live balance and the transactions hypertable, as the replay does) and writes `actual`,
   `abs_error` and `in_band` onto every saved forecast for those days — rescoring if a late purchase
   changed the past.
3. **Aggregate.** `forecast_accuracy_daily` sums those scores per persona, day and lead (1, 7, 14).
   It stores sums and counts, not averages, so any window combines exactly. It reads only
   `forecast_snapshots`: a continuous aggregate can join a plain table, but it wouldn't notice changes
   there and would keep stale scores, so the actual balance lives on the snapshot row instead.
4. **Report.** `GET /forecast`'s `readiness` (whose `rolling_error` the agent quotes as its track record) uses the saved 7-day-ahead
   forecasts once 7 or more of the last 14 days are scored — `rolling_error_source: "saved"`, with
   `band_coverage` — and says "The 7-day-ahead forecasts I saved were off by $X…". Until then it
   replays the engine on past days (`"replay"`) and says "Replayed on your history, …".

## Stack

- **App:** Expo (React Native + Expo Router) + TypeScript → web, iOS, Android from one codebase; react-native-svg charts; Auth0
- **Backend:** Python 3.12, FastAPI, httpx (Nessie), psycopg (Tiger Data), Google Gen AI SDK (Gemini)
- **Hosting:** Vultr (backend + DB + static web export); iOS/Android via EAS preview builds / Expo Go for the demo

## Who may do what (sign-in)

`backend/app/main.py` → `authorize_money()`, with Auth0 token checks from `backend/app/auth/`:

| | Signed out | Signed in |
|---|---|---|
| **Reads** (`/me`, `/spending`, `/p2p`, `/safety-net`, `/forecast`, `/simulate`, `/recurring`, `/agent/chat`) | the demo persona named in `?persona=` — the site stays browsable for judges | **always your own persona**, whatever `?persona=` says |
| **Money** (approve a fix-it, P2P send / request / settle, set a limit, answer a bridge, run the safety net) — real transfers **off** | simulated, nothing moves | simulated, and only as yourself (else 403) |
| **Money** — real transfers **on** (`LIVE_TRANSFERS=1`) | **401** (or 503 if sign-in isn't configured) | only if you own the money (else 403) |

A token that is sent is always fully verified (RS256, issuer, audience, expiry) — a bad one is 401 even on reads.

# Architecture

```
Expo app — web/iOS/Android (Auth0) ──► FastAPI backend (on Vultr)
                                     ├── Nessie client (read + write)
                                     ├── Ingest job ──► Tiger Data (Postgres + TimescaleDB)
                                     │                   ├── transactions hypertable
                                     │                   └── continuous aggregates (daily spend per category)
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
| POST | `/actions/{id}/approve` | executes the Nessie call, returns the new forecast |

## Tiger Data schema (live — source of truth: `backend/app/db/schema.py`)

| Object | Kind | Purpose |
|---|---|---|
| `transactions` | **hypertable** (7-day chunks, compressed after 180 days, segmented by customer) | every purchase, deposit, transfer and paid bill — signed amounts |
| `daily_spend` | **continuous aggregate** (real-time, refreshed every 15 min) | per-day, per-category spend → Spending screen + forecast |
| `accounts` | table | opening balance + time; live balance = opening + transactions since |
| `bills` | table | upcoming recurring bills — the forecast's scheduled outflows |
| `personas`, `merchants` | tables | demo persona ids (+ age), merchant categories |
| `contacts`, `p2p_payments`, `p2p_requests` | tables | peer-to-peer: each contact is a real Nessie customer; every payment keeps both Nessie record ids |

**For the forecast engine and agent** (`backend/app/db/repo.py` — no SQL needed):
`accounts_with_balances(conn, customer_id)`, `transactions(conn, customer_id, since, until)`,
`bills(conn, customer_id)`, `daily_spend(conn, customer_id, start, end)`; get a connection with
`with pool.connection() as conn:` and the customer with `repo.persona(conn, "maya")`.

## Stack

- **App:** Expo (React Native + Expo Router) + TypeScript → web, iOS, Android from one codebase; react-native-svg charts; Auth0
- **Backend:** Python 3.12, FastAPI, httpx (Nessie), psycopg (Tiger Data), Google Gen AI SDK (Gemini)
- **Hosting:** Vultr (backend + DB + static web export); iOS/Android via EAS preview builds / Expo Go for the demo

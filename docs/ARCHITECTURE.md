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
| GET | `/me` | customer + accounts (from Auth0 user → Nessie customer id) |
| GET | `/forecast?days=30` | `{ points: [{date, balance}], low: {date, balance}, events: [...] }` |
| POST | `/simulate` `{amount, date, label}` | same shape as `/forecast`, with the purchase applied |
| GET | `/recurring` | `[{merchant, amount, interval_days, next_date}]` |
| GET | `/spending?month=YYYY-MM` | category totals + transactions *(todo — not in the mock yet)* |
| POST | `/agent/chat` `{message}` | `{reply, tool_calls, pending_action?}` |
| POST | `/actions/{id}/approve` | executes the Nessie call, returns the new forecast |

## Tiger Data schema (draft)

```sql
CREATE TABLE transactions (
  ts          TIMESTAMPTZ NOT NULL,
  account_id  TEXT        NOT NULL,
  kind        TEXT        NOT NULL,   -- purchase | deposit | withdrawal | transfer | bill
  merchant_id TEXT,
  category    TEXT,
  amount      NUMERIC(12,2) NOT NULL, -- negative = money out
  nessie_id   TEXT UNIQUE
);
SELECT create_hypertable('transactions', 'ts');

CREATE MATERIALIZED VIEW daily_spend
WITH (timescaledb.continuous) AS
SELECT time_bucket('1 day', ts) AS day, account_id, category, SUM(-amount) AS spent
FROM transactions WHERE amount < 0
GROUP BY day, account_id, category;
```

## Stack

- **App:** Expo (React Native + Expo Router) + TypeScript → web, iOS, Android from one codebase; react-native-svg charts; Auth0
- **Backend:** Python 3.12, FastAPI, httpx (Nessie), psycopg (Tiger Data), Google Gen AI SDK (Gemini)
- **Hosting:** Vultr (backend + DB + static web export); iOS/Android via EAS preview builds / Expo Go for the demo

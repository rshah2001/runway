# Nessie API notes

Docs: https://api.nessieisreal.com · Base URL: `https://api.nessieisreal.com` · Auth: `?key=YOUR_KEY`
query param on every request. Keep the key in `.env` (`NESSIE_API_KEY`), never in code.

## What we use, and for what

| Feature | Endpoint |
|---|---|
| Balances (checking + savings) | `GET /customers/{id}/accounts` |
| Scheduled outflows | `GET /accounts/{id}/bills` (payment date, recurring) |
| Spending history + categories | `GET /accounts/{id}/purchases` + `GET /merchants/{id}` |
| Income / payday rhythm | `GET /accounts/{id}/deposits` |
| **"Fix it" — move money** | `POST /accounts/{id}/transfers` |
| **"Fix it" — push a bill** | `PUT /bills/{id}` (change `payment_date`) |
| Peer-to-peer IOUs | `POST /accounts/{id}/transfers` to a friend's account |
| Nearest ATM | `GET /atms?lat=&lng=&rad=` |

## How the current Nessie API really behaves (probed Oct 2026 — the public SDKs are outdated)

| Behavior | What we do about it |
|---|---|
| **HTTPS only** — `http://` times out ("Host is down") | Every URL uses `https://` |
| Transactions need `status`: `pending` \| `cancelled` \| `completed` | Always sends `completed` |
| A purchase created *without* `status` breaks `GET /accounts/{id}/purchases` for that account | `create_purchase` always sets it |
| **Balances and amounts are truncated to whole dollars** ($15.49 → 15) | All money fields are written as **integer cents** (`to_cents` / `from_cents` in the client) |
| Balances never change when transactions are created | Live balance = opening balance + transactions since, computed in Tiger Data |
| **Transfers have no destination** (`payee_id` was removed) | "Fix it" = transfer out of savings **+** deposit into checking; the transfer is deleted if the deposit fails |
| Merchant `category` is a string, not a list | Sent as a string |
| Purchases, customers and merchants **can't be deleted**; accounts, bills and transfers can | Seed never duplicates; `--reset` deletes a persona's accounts (taking their purchases) and reuses the customer |
| There is no bulk `DELETE /data` endpoint anymore | — |
| Empty lists sometimes come back as `404 "No X found"` | Client turns them into `[]` |
| ~0.3 s per call | Seed writes in parallel (8 workers): all 3 personas in ~15 s |

## Seeding and syncing

```bash
cd backend
.venv/bin/python -m seed                       # create missing personas (safe to re-run — never duplicates)
.venv/bin/python -m seed --reset maya          # rebuild Maya's accounts + 4 months of history for today
.venv/bin/python -m app.ingest                 # re-sync Nessie → Tiger Data for all personas
```

Persona ids live in the Tiger Data `personas` table, so the whole team (and the server) shares one
dataset. Re-seed with `--reset` on demo morning so "today" in the data is the real today.

## Demo personas (live)

| Persona | Story | Today's balances (checking / savings / card owed) |
|---|---|---|
| **Maya** — UF junior, campus job | Rent lands before payday → dips under the $300 floor → the main demo | $680 / $1,150 / $286.40 |
| **Jordan** — grad student, stipend | 8 subscriptions, $136.39/mo → subscription detective | $1,240 / $400 / $512.80 |
| **Sam** — new grad, first salary | Healthy runway → the "safe to spend" green state | $3,820 / $6,500 / $340.25 |

Definitions: `backend/seed/personas.py`. History is generated deterministically by `backend/seed/plan.py`.

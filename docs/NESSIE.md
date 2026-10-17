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

## Peer-to-peer (built on top of Nessie)

Capital One's challenge calls out peer-to-peer transactions, but current Nessie transfers have no
recipient. So Runway models P2P itself, with every money movement still a real Nessie record:
- each contact (Alex, Riley, Emma, …) is a **real Nessie customer** with a checking account
- a payment = a **transfer** on the sender's account + a **deposit** on the receiver's
  (`app/nessie/moves.py`; the transfer is deleted again if the deposit fails)
- requests / IOUs ("Alex owes you $45") live in Tiger Data — Nessie has no request object — and are
  settled with a real P2P move; settling is an atomic open → settling → paid update, so never twice

## Seeding and syncing

```bash
cd backend
.venv/bin/python -m seed                       # create missing personas (safe to re-run — never duplicates)
.venv/bin/python -m seed --reset maya          # rebuild Maya's accounts + 4 months of history for today
.venv/bin/python -m app.ingest                 # re-sync Nessie → Tiger Data for all personas
```

Persona ids live in the Tiger Data `personas` table, so the whole team (and the server) shares one
dataset. The server re-seeds all three every night at 5 am Eastern, so "today" in the data is always the real today; run `--reset` by hand only to rebuild one sooner.

## Demo personas (live)

| Persona | Age | Story | Balances (checking / savings / card owed) | Peer-to-peer |
|---|---|---|---|---|
| **Maya** | 20 | UF junior on a campus job — rent lands before payday, dips under the $300 floor | $680 / $1,150 / $286.40 | splits with roommate Alex + friend Priya; **Alex owes $45** (concert tickets) |
| **Jordan** | 40 | Parent of two — 8 family subscriptions, ~$164/mo | $2,450 / $3,200 / $1,284.60 | partner Riley sends half of daycare; **Riley owes $86.40**; pays the soccer coach |
| **Sam** | 60 | Pre-retiree, pension on the way — healthy runway | $6,200 / $48,000 / $612.35 | sends daughter Emma $150/mo + grandson Leo an allowance |

Definitions: `backend/seed/personas.py`. History is generated deterministically by `backend/seed/plan.py`.

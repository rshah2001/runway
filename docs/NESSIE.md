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

## Gotchas

- **HTTPS only.** `http://api.nessieisreal.com` just times out ("Host is down"); always use `https://`.
- **The sandbox starts nearly empty.** We seed our own data: `backend/seed/` creates 3 personas
  (e.g. "Maya, paycheck-to-paycheck UF junior") with ~4 months of purchases, deposits and bills.
  Realistic data = a convincing demo.
- **It can be slow or flaky.** Cache every read in Tiger Data. The demo should only depend on Nessie
  for the one live "fix it" write.
- **Seeding is not idempotent.** Store the created customer/account ids (in the DB or `.env`) so
  teammates share one dataset instead of each creating duplicates.
- Dates are strings (`YYYY-MM-DD`). Amounts are positive numbers — direction comes from the endpoint.

## Demo personas (draft)

| Persona | Story |
|---|---|
| **Maya** — UF junior, campus job | Rent lands before payday → overdraft risk → the main demo |
| **Jordan** — grad student, stipend | Subscription creep → subscription detective |
| **Sam** — new grad, first salary | Healthy runway → shows the "safe to spend" green state |

The prototype's Maya numbers (`prototype/index.html`, `PERSONA`) are tuned so the lowest day dips
just under the $300 floor and a $100 savings transfer fixes it — reuse them for the seed.

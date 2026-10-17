# Backend

FastAPI service. Owners: **rshah2001** (routes, Nessie, Tiger Data, deploy) and **Patil-Hemangi** (forecast, agent, auth, evals). Mock-first: every route already returns realistic
data in the final contract shape (`app/schemas.py`) so the app team can build in parallel.

## Run

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q                                      # contract tests — CI runs these on every PR
.venv/bin/uvicorn app.main:app --reload --port 8000     # interactive docs: http://localhost:8000/docs
```

## Layout

```
backend/
├── app/
│   ├── main.py            routes (thin — delegate to modules)
│   ├── schemas.py         the API contract (mirror in app/src/lib/types.ts)
│   ├── config.py          live vs demo mode
│   ├── data.py            what the routes call: live data or demo fallback
│   ├── ingest.py          Nessie → Tiger Data sync (python -m app.ingest)
│   ├── db/                Tiger Data: pool, schema (hypertables + continuous aggregates), repo queries
│   ├── forecast_history.py  saves each day's forecast in Tiger Data and scores it once the day has passed
│   ├── nessie/client.py   real Nessie client (integer cents, retries)
│   ├── nessie/demo.py     demo data for keyless runs
│   ├── forecast/engine.py MOCK schedule → real engine (port of prototype) + ML
│   └── agent/chat.py      MOCK keyword rules → Gemini tool calling + Auth0 approval
├── seed/                  demo personas → Nessie (python -m seed)
└── evals/                 (todo) forecast backtest + agent accuracy suite
```

## Live mode vs demo mode

With `NESSIE_API_KEY` and `DATABASE_URL` in the repo-root `.env`, the API serves **live data**
(Nessie → Tiger Data). Without them — CI, or a teammate with no keys — it serves built-in demo data
with the same shapes. `GET /health` says which (`"mode": "live"` or `"demo"`). Tests always run in demo mode.

## Seed + sync (live mode)

```bash
.venv/bin/python -m seed               # create Maya / Jordan / Sam in Nessie + Tiger Data (never duplicates)
.venv/bin/python -m seed --reset maya  # rebuild a persona for today
.venv/bin/python -m app.ingest         # re-sync Nessie → Tiger Data
```

See `docs/NESSIE.md` for how the current Nessie API behaves (integer cents, no transfer payee, …).

Try it: `POST /agent/chat {"message": "can I afford $180?"}`, then `{"message": "fix it"}`, then
approve the returned action at `POST /actions/{id}/approve`.

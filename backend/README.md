# Backend

FastAPI service. Owners: **team lead + Claude**. Mock-first: every route already returns realistic
data in the final contract shape (`app/schemas.py`) so the app team can build in parallel.

## Run

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload --port 8000     # interactive docs: http://localhost:8000/docs
```

## Layout

```
backend/
├── app/
│   ├── main.py            routes (thin — delegate to modules)
│   ├── schemas.py         the API contract (mirror in app/src/lib/types.ts)
│   ├── nessie/client.py   MOCK → real Nessie client
│   ├── forecast/engine.py MOCK schedule → real engine (port of prototype) + ML
│   └── agent/chat.py      MOCK keyword rules → Gemini tool calling + Auth0 approval
├── seed/                  (todo) create demo personas in Nessie
└── evals/                 (todo) forecast backtest + agent accuracy suite
```

Try it: `POST /agent/chat {"message": "can I afford $180?"}`, then `{"message": "fix it"}`, then
approve the returned action at `POST /actions/{id}/approve`.

# Backend

FastAPI service (Python 3.12). Owners: **A** (data + infra), **B** (forecast + ML), **C** (agent + auth).

Planned modules:

```
backend/
├── seed/        create demo personas in Nessie (run once, store ids)
├── nessie/      thin typed client over the Nessie REST API
├── ingest/      Nessie → Tiger Data sync
├── forecast/    projection engine (ported from prototype/ buildEvents + project) + ML upgrade
├── agent/       Gemini tool definitions + pending-action approval flow
├── evals/       forecast backtest + agent accuracy suite
└── main.py      FastAPI routes (see docs/ARCHITECTURE.md)
```

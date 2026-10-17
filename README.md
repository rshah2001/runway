# Runway 🛫

**Will I be okay?** Runway forecasts your bank balance day by day for the next 30+ days, flags the
day you'd overdraft, and lets an AI banker fix it with one tap — through real Nessie API calls.

Built at **SwampHacks XII** for the Capital One "Best Use of Nessie" challenge.

> **The demo moment:** Maya's chart dips red on Nov 5 — rent + card payment hit before payday.
> She asks *"Can I go to the concert Friday? $180."* The agent says *"Not safely — you'd be short on
> the 5th."* She says *"Fix it."* It proposes moving $100 from savings, she approves the transfer on
> her phone (Auth0), a real Nessie transfer runs, and the chart turns green.

## Start here

| If you want to… | Read |
|---|---|
| Understand the plan, prizes, and who does what | [`docs/PLAN.md`](docs/PLAN.md) |
| See the system design and API contract | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) |
| Work with Nessie | [`docs/NESSIE.md`](docs/NESSIE.md) |
| Give your AI coding tool context | [`CLAUDE.md`](CLAUDE.md) |
| See the working UI prototype | open [`prototype/index.html`](prototype/index.html) in a browser |

## Repo layout

```
runway/
├── prototype/      single-file HTML prototype — the reference UI + forecast logic (demo data)
├── frontend/       Next.js app (Auth0 login, runway chart, agent chat)        — owner: D
├── backend/        FastAPI: Nessie client, Tiger Data, forecast, Gemini agent — owners: A, B, C
├── docs/           plan, architecture, Nessie notes
└── CLAUDE.md       shared context for AI coding assistants
```

## Run the prototype

```bash
cd prototype && python3 -m http.server 8000
# open http://localhost:8000 — pick any password (it only encrypts local demo data)
```

All data in the prototype is a **fictional persona ("Maya")** generated relative to today's date.

## Prior work disclosure

The `prototype/` UI and forecast engine were adapted from a pre-existing personal-finance project by
a team member, with all personal data removed. We will disclose this on Devpost and confirm with the
organizers that it's allowed. Everything in `frontend/` and `backend/` is built during the hackathon.

## Secrets

Never commit API keys. Copy `.env.example` to `.env` and fill it in locally.

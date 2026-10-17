# Runway 🛫

**[sixsevenbucksleft.vip](https://sixsevenbucksleft.vip)** · *you're a VIP… with sixty-seven bucks left*

**Will I be okay?** Runway shows how much runway you have before you run out of money. It forecasts your bank balance day by day for the next 30+ days, flags the
day you'd overdraft, and lets an AI banker fix it with one tap — through real Nessie API calls.

Built at **SwampHacks XII** for the Capital One "Best Use of Nessie" challenge.

> **The demo moment:** Maya's chart dips red on Nov 5 — rent + card payment hit before payday.
> She asks *"Can I go to the concert Friday? $180."* The agent says *"Not safely — you'd be short on
> the 5th."* She says *"Fix it."* It proposes moving $100 from savings, she approves the transfer on
> her phone (Auth0), a real Nessie transfer runs, and the chart turns green.

## Start here

| If you want to… | Read |
|---|---|
| Understand the plan and prizes | [`docs/PLAN.md`](docs/PLAN.md) |
| Pitch: how we're different + how it learns | [`docs/WHY_RUNWAY.md`](docs/WHY_RUNWAY.md) |
| See who owns which files + your starter prompt | [`docs/TEAM.md`](docs/TEAM.md) · [`docs/TEAM_PROMPTS.md`](docs/TEAM_PROMPTS.md) |
| See the system design and API contract | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) |
| Work with Nessie | [`docs/NESSIE.md`](docs/NESSIE.md) |
| Family safety net (headline feature) | [`docs/SAFETY_NET.md`](docs/SAFETY_NET.md) |
| Deploy / CI-CD to Vultr | [`docs/DEPLOY.md`](docs/DEPLOY.md) |
| Give your AI coding tool context | [`CLAUDE.md`](CLAUDE.md) |
| See the working UI prototype | open [`prototype/index.html`](prototype/index.html) in a browser |

## Repo layout

```
runway/
├── prototype/      single-file HTML prototype — the reference UI + forecast logic (demo data)
├── app/            Expo app → web + iOS + Android (Today, Ask, Spending)      — an2thu
├── backend/        FastAPI: Nessie + Tiger Data (rshah2001) · forecast + agent + evals (Patil-Hemangi)
├── deploy/         Docker + Caddy config for the Vultr server
├── .github/        CI (tests, lint, web build) + auto-deploy to Vultr on main
├── docs/           plan, architecture, Nessie notes
└── CLAUDE.md       shared context for AI coding assistants
```

## Run it

```bash
# terminal 1 — backend (serves mock data in the final API shape)
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload --port 8000

# terminal 2 — app
cd app && npm install && npx expo start      # w = web · i = iOS · a = Android · or scan with Expo Go
```

## Run the prototype

```bash
cd prototype && python3 -m http.server 8080
# open http://localhost:8080 — pick any password (it only encrypts local demo data)
```

All data in the prototype is a **fictional persona ("Maya")** generated relative to today's date.

## Prior work disclosure

The `prototype/` UI and forecast engine were adapted from a pre-existing personal-finance project by
a team member, with all personal data removed. We will disclose this on Devpost and confirm with the
organizers that it's allowed. Everything in `app/` and `backend/` is built during the hackathon.

## Secrets

Never commit API keys. Copy `.env.example` to `.env` and fill it in locally.

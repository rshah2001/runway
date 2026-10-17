# Starter prompts

Paste your prompt into your AI coding assistant (Claude Code, Cursor, …) from the repo root. Each
prompt restates the file-ownership rules from `docs/TEAM.md` so parallel work never collides.

---

## an2thu — App UI + design (plan role D)

```
You're working on Runway (live at sixsevenbucksleft.vip), a hackathon banking app: one Expo / React Native codebase that ships a
website, an iOS app and an Android app. First read CLAUDE.md, docs/PLAN.md, docs/TEAM.md,
docs/ARCHITECTURE.md and app/AGENTS.md, then open prototype/index.html in a browser — it is the
visual reference (dark glass cards, gradient accents, runway chart).

My job: every screen and the whole look of the app. We are going for the "Easy On The Eyes" prize.

I own app/** EXCEPT app/src/lib/auth.ts (Patil-Hemangi owns auth logic; I only call its functions).
Do NOT edit backend/**, deploy/**, .github/**. Do not change app/src/lib/types.ts or api.ts without
telling me first — they are the shared API contract and need a separate PR.

Data comes from the `api` object in app/src/lib/api.ts (types in app/src/lib/types.ts). The backend
serves mock data in the final shape. Run it locally with:
  cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/uvicorn app.main:app --reload
(or point EXPO_PUBLIC_API_URL in app/.env at the shared Vultr server once it is up).

Build, in order:
1. Theme: port the prototype's dark palette and card style into app/src/constants/theme.ts.
2. Today: status card (green / amber / red from forecast.low vs forecast.safe_floor), the 30-day
   runway line chart with the low point marked and a dashed safe-floor line (react-native-svg —
   `git pull` then `npx expo install react-native-svg`), a "safe to spend" number
   (max(0, low − safe_floor)), and a "Coming up" list from forecast.events (next 14 days).
   Pull-to-refresh.
3. Ask: chat bubbles, input, suggested-prompt chips ("Can I afford $180 Friday?", "Fix it",
   "What subscriptions do I have?") using api.chat(). When a reply has pending_action, show an
   approval card (description, amount, Approve / Decline → api.approve(id)), then refresh Today so
   the chart visibly turns green — that is the demo's big moment. If approve returns 503 show
   "nothing moved — try again"; if it returns 502 (status "failed") show "we're checking with the
   bank" and do NOT offer a retry.
4. Spending: api.spending(month, persona) gives real data from Tiger Data — category totals (biggest
   first), a daily spend series for a chart, and the transaction list (newest first). Add a month
   picker. Subscriptions from api.recurring() with monthly + yearly totals; live balances from
   api.me(persona).
5. Persona switcher: api.personas() returns maya / jordan / sam — a small picker (e.g. on Today)
   lets the demo jump between the overdraft story, subscription creep and a healthy runway. Pass
   the chosen slug to api.me / api.spending.
6. Login screen (app/src/app/login.tsx) that calls login() from app/src/lib/auth.ts.
7. Polish: icons, splash, empty/loading/error states, animations. Must look great on web AND phone.

Before each push: `cd app && npx expo lint && npx expo export -p web` (CI runs the same).
Branch names: ui/<feature>. Small PRs.
```

---

## Patil-Hemangi — AI + auth (plan roles B + C)

```
You're working on Runway (live at sixsevenbucksleft.vip), a hackathon banking app built on the Capital One Nessie API. First read
CLAUDE.md, docs/PLAN.md (especially "AI depth" and the core design decision), docs/TEAM.md and
docs/ARCHITECTURE.md (the "Fix it" flow).

My job: everything the AI-track judges will read — the forecast model, the recurring-transaction
detector, the Gemini agent, the evals — plus Auth0 (login + approval before money moves).

I own: backend/app/forecast/**, backend/app/agent/**, backend/app/auth/**, backend/evals/**,
app/src/lib/auth.ts. Do NOT edit backend/app/main.py, backend/app/nessie/**, deploy/**, or app
screens — if I need a route or contract change, stop and tell me so I can coordinate with the team.
The API contract (backend/app/schemas.py) must not change shape without a separate PR.

Non-negotiable design rules (judges will ask about them):
- The LLM never does math. Gemini picks tools and explains results; every number comes from the
  deterministic forecast engine.
- The agent never moves money directly. Write tools create a PendingAction; nothing executes until
  the user approves it (Auth0).

Run the backend: cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
then .venv/bin/pytest (tests must stay green) and .venv/bin/uvicorn app.main:app --reload.

Build, in order:
1. forecast/engine.py: replace the mock schedule with a real engine — port buildEvents + project
   from prototype/index.html to typed Python. Keep the public function signatures. Real data is
   already in Tiger Data: use backend/app/db/repo.py (accounts_with_balances, transactions, bills,
   daily_spend — see "For the forecast engine" in docs/ARCHITECTURE.md). Maya / Jordan / Sam have
   4 months of history each; months 1–3 vs 4 is your backtest split.
2. Recurring detector: group purchases by merchant, find stable interval + amount → recurring().
3. agent/chat.py: Gemini tool calling (get_forecast, simulate_purchase, find_recurring,
   propose_transfer). Check the current Google Gen AI SDK docs, don't rely on memory. Cap message
   length. Keep the PendingAction flow.
4. evals/: (a) forecast backtest — fit on months 1–3 of seeded history, predict month 4, report
   MAE/MAPE; (b) agent eval — 30–50 "can I afford $X on day Y?" cases with ground truth from the
   engine; report tool-selection and answer accuracy. Results table goes in the README.
5. Auth0: login for the app (app/src/lib/auth.ts exporting login/logout/getAccessToken — check the
   current Auth0 docs for Expo; native may need a dev build), backend token verification
   (backend/app/auth/), and approval before /actions/{id}/approve executes (the TODO(auth) in
   main.py — tell me the exact change and I'll wire it in). Bonus: Auth0 for AI Agents async
   authorization (push approval on the phone).

Write clean, documented, typed code with tests — the AI judges read the repo.
Branch names: ai/<feature>. Small PRs.
```

---

## rshah2001 + Claude — Data + backend (plan role A)

```
Mock-first backend; the contract lives in backend/app/schemas.py. Replace mocks without changing shapes:
1. nessie/client.py — real Nessie client + seed script (backend/seed/) for Maya / Jordan / Sam.
2. Tiger Data — transactions hypertable + daily_spend continuous aggregate; ingest from Nessie.
3. Wire Patil-Hemangi's auth dependency into the routes; resolve TODO(auth) on /actions/{id}/approve.
4. Vultr deploy (deploy/ + .github/workflows/ci.yml) and the GoDaddy domain.
```

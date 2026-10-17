# Starter prompts

Each teammate pastes their prompt into their AI coding assistant (Claude Code, Cursor, …) from the
repo root. The prompts restate the file-ownership rules from `docs/TEAM.md` so parallel work doesn't collide.

---

## Friend 1 — Today + Spending screens

```
You're working on Runway, a hackathon banking app (Expo / React Native → web, iOS, Android).
First read CLAUDE.md, docs/PLAN.md, docs/TEAM.md, app/AGENTS.md, and skim prototype/index.html
(the visual + logic reference — open it in a browser to see it).

My job: the Today and Spending screens.

Files I own (only edit these):
  app/src/app/index.tsx, app/src/app/spending.tsx,
  app/src/components/today/**, app/src/components/spending/**, app/src/components/charts/**,
  app/src/constants/theme.ts, app/assets/**
Do NOT edit: backend/**, app/src/lib/types.ts, app/src/lib/api.ts, navigation/tab files, the Ask
screen, or anything auth-related. If I need a contract change, stop and tell me so I can ask the team.

Data: use the `api` object in app/src/lib/api.ts (api.forecast(), api.recurring(), api.me(),
api.simulate()). Types are in app/src/lib/types.ts. The backend serves mock data — run it with:
  cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/uvicorn app.main:app --reload

Build:
1. Theme: port the prototype's dark palette (--bg, --card, --green, --red, --amber, gradient) into
   theme.ts and make the app look like the prototype.
2. Today screen: a status card (green "You're okay" / amber / red "Tight — needs a move" based on
   forecast.low vs forecast.safe_floor), the 30-day runway line chart with the low point marked and
   a dashed safe-floor line (use react-native-svg — install with `npx expo install react-native-svg`
   after `git pull`), "safe to spend" number (low − safe_floor, min 0), and a "Coming up" list from
   forecast.events (next 14 days).
3. Spending screen: subscriptions list from api.recurring() with a monthly + yearly total
   ("subscription detective"), and accounts from api.me().
4. Must work on web AND on a phone (Expo Go). Pull-to-refresh on Today.

Before each commit: `cd app && npx expo lint`. Work on branch f1/<feature>, open small PRs.
```

---

## Friend 2 — Ask screen, Auth0, shipping

```
You're working on Runway, a hackathon banking app (Expo / React Native → web, iOS, Android).
First read CLAUDE.md, docs/PLAN.md, docs/TEAM.md, app/AGENTS.md, and docs/ARCHITECTURE.md
(especially the "Fix it" flow).

My job: the Ask (agent chat) screen, Auth0 login, and getting the app shipped.

Files I own (only edit these):
  app/src/app/ask.tsx, app/src/app/login.tsx, app/src/components/chat/**, app/src/lib/auth.ts,
  app/eas.json
Do NOT edit: backend/**, app/src/lib/types.ts, app/src/lib/api.ts, the Today/Spending screens,
theme.ts. If I need a contract or navigation change, stop and tell me so I can ask the team.

Data: use api.chat(message) and api.approve(actionId) from app/src/lib/api.ts. The backend serves a
mock agent — try "can I afford $180?" and "fix it". Run it with:
  cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/uvicorn app.main:app --reload

Build:
1. Ask screen: chat bubbles, a text input, suggested-prompt chips ("Can I afford $180 Friday?",
   "Fix it", "What subscriptions do I have?"). When a reply includes pending_action, render an
   approval card (description + amount, Approve / Decline). Approve calls api.approve(id) and shows
   a success state. Keyboard-safe on iOS and Android.
2. Auth0 login: read the current Auth0 docs for Expo / React Native (do not rely on memory — check
   which SDK supports web + native in our Expo SDK version; native Auth0 may need a development
   build instead of Expo Go). Put all auth logic in app/src/lib/auth.ts and the screen in login.tsx.
   When it works, tell me exactly what one-line change _layout.tsx needs so I can PR it.
3. Shipping: `eas.json` for iOS/Android preview builds, and a web export (`npx expo export -p web`).
4. Non-code: register the domain (GoDaddy Registry via MLH), start the Devpost draft, and write the
   3-minute demo script from docs/PLAN.md into docs/DEMO.md.

Before each commit: `cd app && npx expo lint`. Work on branch f2/<feature>, open small PRs.
```

---

## Backend (team lead + Claude) — next steps

```
Backend is mock-first and the contract lives in backend/app/schemas.py. Replace mocks one module at a
time without changing response shapes:
1. nessie/client.py — real Nessie client + seed script (backend/seed/) for Maya/Jordan/Sam.
2. Tiger Data — transactions hypertable + daily_spend continuous aggregate; ingest from Nessie.
3. forecast/engine.py — port the prototype's buildEvents/project; then the ML upgrade + backtest eval.
4. agent/chat.py — Gemini tool calling over the forecast tools; Auth0 approval gate on /actions/{id}/approve.
5. Deploy to Vultr.
```

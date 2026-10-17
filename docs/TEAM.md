# Team split — who owns what

Three workstreams that never edit the same files. Everything is **mock-first**: the backend already
serves realistic fake data in the final contract shape, so nobody waits on anybody.

| Workstream | Who | Plan role | Owns (only they edit these) |
|---|---|---|---|
| **Data + backend** | **rshah2001** (+ Claude) | A | `backend/app/main.py`, `backend/app/nessie/**`, `backend/app/db/**`, `backend/seed/**`, `deploy/**`, `.github/**` |
| **App UI + design** | **an2thu** | D | `app/**` except `app/src/lib/auth.ts` — every screen, the chart, chat UI, approval cards, login screen, theme, assets; slides + demo video |
| **AI + auth** | **Patil-Hemangi** | B + C | `backend/app/forecast/**`, `backend/app/agent/**`, `backend/app/auth/**`, `backend/evals/**`, `app/src/lib/auth.ts` |

How the Auth0 work divides: **Patil-Hemangi** owns the Auth0 tenant, `app/src/lib/auth.ts`
(`login()`, `logout()`, `getAccessToken()`), backend token verification, and the approval gate on
money moves. **an2thu** builds the login screen and approval cards that call those functions.

## Shared files — change only via a small PR, and say so in the group chat first

- `backend/app/schemas.py` + `app/src/lib/types.ts` — the API contract. Always change both together.
- `app/src/lib/api.ts` — add a method when a new endpoint lands; don't restructure it.
- `backend/requirements.txt`, `app/package.json` + lockfile — **`git pull` right before adding a
  dependency** (`npx expo install <pkg>` in `app/`), commit it on its own, push right away.

## Git + CI rules

- Branch per feature: `ui/today-chart`, `ai/gemini-tools`, `be/nessie-client`. Small PRs, squash-merge.
- **CI runs on every PR** (backend tests, app lint, web build). Don't merge red.
- **Merging to `main` auto-deploys to Vultr** — `main` must always be demo-able.
- Rebase on `main` often. Never force-push `main`. No secrets in git — `.env` is ignored.

## Staying in sync in real time

- Point the app at the **shared Vultr backend** (`EXPO_PUBLIC_API_URL` in `app/.env`) to see backend
  changes about a minute after they merge — no pulling needed. Run the backend locally only when
  you're changing it.
- Live API docs for whatever is deployed: `<server>/api/docs`.
- `npx expo start --tunnel` → anyone can scan the QR code and see your app live on their phone.

## Sync points

| When | What |
|---|---|
| Hour 2 | Everyone runs the app against the mock backend; Vultr server up |
| Hour 8 | Today screen shows a real chart; Ask screen sends a message and renders the reply |
| Hour 16 | Real Nessie + Tiger Data + Gemini behind the same contract — app needs **no changes** |
| Hour 22 | Feature freeze; record backup video |

# Team split — who owns what

Three workstreams that never edit the same files. The app is built **mock-first**: the backend already
serves realistic fake data in the final contract shape, so the app team never waits on the backend.

| Workstream | People | Owns (only they edit these) |
|---|---|---|
| **Backend** | Team lead + Claude | `backend/**` |
| **App: Today + Spending** | Friend 1 | `app/src/app/index.tsx`, `app/src/app/spending.tsx`, `app/src/components/today/**`, `app/src/components/spending/**`, `app/src/components/charts/**`, `app/src/constants/theme.ts`, `app/assets/**` |
| **App: Ask + Auth + Ship** | Friend 2 | `app/src/app/ask.tsx`, `app/src/app/login.tsx`, `app/src/components/chat/**`, `app/src/lib/auth.ts`, `app/eas.json`, Devpost / slides / demo video |

## Shared files — change only via a small PR, and say so in the group chat first

- `backend/app/schemas.py` + `app/src/lib/types.ts` — the API contract. Always change both together.
- `app/src/lib/api.ts` — add a method when a new endpoint lands; don't restructure it.
- `app/src/app/_layout.tsx`, `app/src/components/app-tabs.tsx`, `app/src/components/app-tabs.web.tsx` — navigation.
- `app/package.json` / lockfile — **`git pull` right before `npx expo install`**, commit immediately, push.

## Git rules

- Branch per feature: `f1/today-chart`, `f2/ask-chat`, `be/nessie-client`. Small PRs, squash-merge.
- Rebase on `main` often. Never force-push `main`.
- No secrets in git — `.env` is ignored; share keys in the group chat, not in code.

## Sync points

| When | What |
|---|---|
| Hour 2 | Everyone runs the app against the mock backend on their own laptop |
| Hour 8 | Today screen shows a real chart; Ask screen sends a message and renders the reply |
| Hour 16 | Backend swaps mocks for real Nessie + Gemini — app needs **no changes** if the contract held |
| Hour 22 | Feature freeze; deploy; record backup video |

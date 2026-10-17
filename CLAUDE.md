# Six Seven Bucks Left — context for AI coding assistants

(Product name: **Six Seven Bucks Left**, at sixsevenbucksleft.vip. The repo, folders, server paths and bundle ids keep the internal codename `runway`.)

Hackathon project (SwampHacks XII). A balance-forecasting banking app on the Capital One **Nessie** API
with a **Gemini** agent that can move money only after **Auth0** approval. Read `docs/PLAN.md` for
goals and prizes and `docs/ARCHITECTURE.md` for the API contract before making changes.

## Non-negotiables

- **The LLM never does math.** All balances, forecasts and affordability answers come from the
  deterministic forecast engine, exposed to Gemini as tools. Don't let the model compute numbers.
- **The agent never moves money directly.** Write actions (transfers, bill changes) create a pending
  action that requires user approval via Auth0 before any Nessie POST/PUT.
- **No secrets in git.** Keys live in `.env` (see `.env.example`). Never hardcode the Nessie key.
- **No real personal data.** Only the fictional demo personas. The repo will be public for judging.
- **The API contract is `backend/app/schemas.py` ↔ `app/src/lib/types.ts`.** Change both in one PR, so app and backend stay in sync.

## Code quality (the AI-track judges read the code)

- Small, well-named functions; docstrings on public functions; explain *why* in comments, not *what*.
- Type hints in Python, TypeScript strict mode in the app.
- Every model/agent change should keep `backend/evals/` passing and update the eval results in the README.

## Layout

- `prototype/index.html` — working single-file reference. The forecast logic (`buildEvents`, `project`,
  `verdictFor`, `coachAdvice`) is the spec for the backend engine; its CSS is the visual spec for the app.
- `backend/` — FastAPI: Nessie client, Tiger Data ingest, forecast engine, Gemini agent, evals. Mock-first.
- `app/` — Expo (React Native + Expo Router) → web, iOS, Android. Read `app/AGENTS.md` before touching Expo APIs.
- **File ownership is in `docs/TEAM.md` — only edit files your workstream owns.**

## Workflow

- Branch per feature (`be/…`, `ui/…`, `ai/…`), small PRs, one teammate reviews.
- CI must be green before merging. **Merging to `main` auto-deploys to Vultr**, so `main` must always be demo-able.
- Don't push directly to `main` after hour 2.

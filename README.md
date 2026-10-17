# Runway 🛫

**[sixsevenbucksleft.vip](https://sixsevenbucksleft.vip)** · *you're a VIP… with sixty-seven bucks left*

**Banking apps tell you what already happened. Runway tells you the exact day you'll run short, and
fixes it before it happens.** It forecasts your checking balance day by day from your Capital One
(Nessie) accounts, warns you days ahead of an overdraft, and covers the dip from your own savings or
from family who agreed to help, with real Nessie money, always within limits a person set.

Built at **SwampHacks XII** for Capital One's **Best Use of Nessie** challenge.

> **The demo:** Maya (20) will dip under her $300 floor on Nov 5, when rent lands before payday. Nobody
> has to ask: Runway sees the dip, checks that grandpa Sam (60) can help safely, and moves $100 within
> the limit *he* set. When it's over his limit, **Sam's phone buzzes** (Auth0 push) and he approves.
> On payday it goes back automatically: *"💸 You got your $100 back from Maya."* Maya can also ask the
> assistant *"Can I go to the concert Friday? $180"* and get an honest answer with the real numbers.

## What it does

- **Today:** a day-by-day balance line for the next month, the day you'd dip, a range of how low it
  could go, and how sure Runway is ("calibrating" → "learning" → "confident").
- **Family safety net:** each person sets how much Runway may move from *them* to someone else without
  asking; it must come back by the borrower's next payday, and helping must keep the helper safe too.
- **Assistant:** ask *"can I afford $X on Friday?"*, *"fix it"*, *"who owes me money?"*. It answers in
  a voice that fits you (by age), and it **proposes**; people **approve**.
- **Spending + peer-to-peer:** categories, subscriptions it detected, IOUs, and real transfers between
  real Nessie customers.

## How the AI works

```
Nessie ──sync──► Tiger Data ──► forecast engine (deterministic) ──► tools ──► Gemini ──► reply
                                      │                                        │
                                      └──► safety net (acts within limits)     └─ any $ figure no tool
                                                                                  produced → reply thrown away
```

**The LLM never does maths.** Gemini picks which tool to call and explains the result in plain words.
Every number (balances, dates, shortfalls, transfer amounts) comes from the deterministic engine in
`backend/app/forecast/`. This is **enforced at runtime**: a reply quoting any dollar figure no tool
returned is discarded and a rule-based answer is given instead (`backend/app/agent/chat.py`). Money only
moves through a pending action the user approves; the persona always comes from the signed-in user,
never from the model.

**The forecast engine** (`backend/app/forecast/`), learned per person from their own history:
- **Paydays and fixed transfers** found by a recurring-transaction detector (steady cadence + steady
  amount). Two matching paychecks give a *provisional* payday; three confirm it.
- **Everyday spending rate** from the last 90 days; big one-off purchases (a car repair) are flagged and
  kept out of the rate.
- **A range, not a point:** a block bootstrap of the person's own days, **calibrated on outside bank
  data** (split conformal), so its cautious end is beaten about 5% of the time, as promised.
- **Readiness**, like a fitness tracker's calibration period: it says how sure it is and why, and it
  saves each day's forecast in Tiger Data to grade itself later ("my 7-day forecasts were off by $X").
- **Voices:** Gen Z for under-30s (one steady, mild voice), direct for 30–49, courteous for 50+. The
  mood follows the money: calm and plain when you're about to run short.

## Evals: measured, not claimed

Full method and tables: [`backend/evals/README.md`](backend/evals/README.md) · ML on outside data:
[`ml/README.md`](ml/README.md). The evals run in CI, so a change that makes the AI worse fails the build.

| What | Result |
|---|---|
| **Agent** (Gemini, 42 "can I afford / fix it / subscriptions / forecast" questions across 3 voices) | **100%** tool selection · **95%** correct answers · **100%** of $ figures traceable to the engine |
| **Agent, offline baseline** (48 questions incl. peer-to-peer) | 100% / 100% / 100% |
| **Forecast backtest** (learn months 1–3, predict month 4, 18 folds) | daily balance error **$138**: −66% vs ignoring everyday spending, −16% vs repeating last month |
| **Learning curve** (only 30 days of history) | error **$2,737 → $206** with provisional paydays |
| **Range calibration** (cautious end beaten, target 5%) | **12–43% → 4–11%** on held-out IBM card users and a real UK account it never trained on |
| **Tone** (Gen Z voice stays itself when money is tight or fine; rule-based checks on real Gemini replies) | **3/6 → 6/6** |

## Design choices and trade-offs

- **Rules + small statistics, not a deep model, for the forecast.** A few months of one person's history
  supports a handful of means, not a neural net. We *tried* a LightGBM spending model on IBM's card users: it
  beat the flat average by 2% where it was trained and lost everywhere else, because spending habits
  don't overlap between populations (`ml/README.md`). So the forecast keeps the simple model, with
  evidence, and the learned part is the calibration of its uncertainty.
- **Tested on outside data, not just our own.** Our seeded personas come from our own generator, which
  flatters any model, so the range was checked on IBM TabFormer, a real UK account (MoneyData) and 4,500
  real Czech accounts (Berka). The cost: on our own personas the range is wider than they need.
- **Honest about not knowing.** A forecast with a provisional payday or too little history never calls
  itself "confident", and readiness explains why in plain words.
- **People stay in control of money.** The agent proposes; the user approves (Auth0). Under a family
  limit the lender pre-authorised it; over it, the lender approves on their phone.
- **Sandbox limits, said out loud.** In production, ownership comes from the bank's own login and each
  customer grants their own token. In Nessie, one API key lives only on the server and every money move
  checks the signed-in owner first. Only the data connector is bank-specific.

## Built with

| | Used for |
|---|---|
| **Capital One Nessie** | the bank: customers, accounts, merchants, purchases, deposits, bills, transfers; every money move is a real Nessie record ([`docs/NESSIE.md`](docs/NESSIE.md)) |
| **Gemini** (`gemini-3.8-flash`) | the assistant: tool calling over the forecast engine |
| **Auth0** | sign-in, owner-only money moves, and push approvals on the lender's phone (CIBA) |
| **Tiger Data** (TimescaleDB) | transactions and saved forecasts as hypertables; continuous aggregates for daily spend and forecast accuracy |
| **Vultr** | backend + database hosting, auto-deployed from `main` |
| **GoDaddy** | the domain, [sixsevenbucksleft.vip](https://sixsevenbucksleft.vip) |
| **Expo** (React Native) | one codebase for web, iOS and Android |

## Repo layout

```
runway/
├── app/            Expo app → web + iOS + Android (Today, Spending, Family; assistant sheet)
├── backend/        FastAPI: Nessie + Tiger Data, forecast engine, agent, safety net, evals
│   ├── app/forecast/   the deterministic engine, readiness, range, report card
│   ├── app/agent/      Gemini tool calling, voices, grounding guard
│   └── evals/          agent, backtest, learning curve and tone evals
├── ml/             outside datasets, calibration and model experiments (see ml/README.md)
├── deploy/         Docker + Caddy config for the Vultr server
├── docs/           architecture, Nessie notes, family safety net, deploy
└── prototype/      the original single-file HTML prototype (demo data)
```

## Run it

```bash
# backend — demo data out of the box; live Nessie + Tiger Data when .env has the keys
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/uvicorn app.main:app --reload --port 8000

# app
cd app && npm install && npx expo start      # w = web · i = iOS · a = Android

# tests and evals (from backend/)
.venv/bin/pytest -q
.venv/bin/python -m evals.forecast_backtest
.venv/bin/python -m evals.agent_eval          # add --gemini to score Gemini (needs GEMINI_API_KEY)
```

More: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) (system design and API) ·
[`docs/SAFETY_NET.md`](docs/SAFETY_NET.md) · [`docs/DEPLOY.md`](docs/DEPLOY.md) ·
[`docs/WHY_RUNWAY.md`](docs/WHY_RUNWAY.md) (pitch notes).

## Team

- **Rishil Shah** ([@rshah2001](https://github.com/rshah2001)): data and backend, Nessie + Tiger Data, deploy
- **Hemangi Patil** ([@Patil-Hemangi](https://github.com/Patil-Hemangi)): forecast model, AI agent, evals, ML
- **[@an2thu](https://github.com/an2thu)**: app UI and design

## Prior work disclosure

The `prototype/` UI and forecast engine were adapted from a pre-existing personal-finance project by
a team member, with all personal data removed. We will disclose this on Devpost and confirm with the
organizers that it's allowed. Everything in `app/`, `backend/` and `ml/` was built during the hackathon.

All people, balances and histories in the demo are fictional. Never commit API keys: copy `.env.example`
to `.env` and fill it in locally.

# Runway 🛫

**[sixsevenbucksleft.vip](https://sixsevenbucksleft.vip)** · *you're a VIP… with sixty-seven bucks left*

**Most banking apps tell you when you're running out of money. Runway makes sure you don't have to face
that moment alone.** It forecasts your checking balance day by day from your Capital One (Nessie)
accounts, sees a shortfall coming, and quietly arranges help from people who already agreed to help —
**without anyone seeing anyone else's balance**, and only when helping is safe for the helper too.

*Support without the spotlight.* Built at **SwampHacks XII** for Capital One's **Best Use of Nessie** challenge.

> **The demo:** Maya (20) will be **$135** short before payday. She doesn't ask anyone. Runway's
> **Network Guardian** checks the people who agreed to help her: grandpa Sam authorized $150, but a loan
> payment lands before Maya can repay, so his *safe* amount is **$90**; Jordan authorized $300, but his
> mortgage is due that week, so **$0**; cousin Emma can give **$45**. Runway moves **Sam $90 + Emma $45**
> as two real Nessie transfers. Sam sees *"$90 with Maya, expected back Fri"* — never her balance, her
> spending, or that Emma helped too. On Maya's next **verified** payday it goes back automatically.

## What it does

- **Today:** a day-by-day balance line for the next month, the day you'd dip, a cautious range, how sure
  Runway is, and **Your safety net** — who's ready to cover you, or what's out right now.
- **Circles + Quiet Support Agreements:** support between family *and* friends needs **both** people's
  yes. The supporter sets a limit; the recipient opts in; either can stop at any time. Joining a circle
  grants nothing — consent is per relationship, versioned and audited.
- **Network Guardian:** sizes each supporter's *safe* contribution from their own cautious forecast over
  the whole time the money is out, splits a need across several supporters, and re-checks everything under
  database locks right before money moves. Repayment waits for a real paycheck and never causes a new dip.
- **Assistant (Gemini):** *"can I afford $X on Friday?"*, *"fix it"*, *"who's covering me?"*, *"what can I
  cut until payday?"*, *"brief me on my week"* — in a voice that fits you. It **proposes**; people
  **approve**. Ask it about someone else's money and it tells you nobody in Runway can see that.
- **Spending + peer-to-peer:** categories, detected subscriptions, IOUs, and real transfers between real
  Nessie customers — each tap pays exactly once.

## How the AI works

```
Nessie ──sync──► Tiger Data ──► forecast engine (deterministic) ──► tools ──► Gemini ──► reply
                                      │                              ▲          │
                                      │                 privacy guard┘          └─ any $ figure no tool
                                      ▼                                            produced → reply thrown away
               Network Guardian (pure) ── consent + locks + journal ──► real Nessie transfers ──► reconcile
```

**The LLM never does maths.** Gemini picks which tool to call and explains the result in plain words.
Every number (balances, dates, shortfalls, transfer amounts) comes from the deterministic engine in
`backend/app/forecast/`. This is **enforced at runtime**: a reply quoting any dollar figure no tool
returned is discarded and a rule-based answer is given instead (`backend/app/agent/chat.py`). Money only
moves through a pending action the user approves; the persona always comes from the signed-in user,
never from the model.

**The Network Guardian** (`backend/app/guardian.py`, pure, no LLM): a supporter's safe capacity is
`min(cautious p5 balance over the lending window − their own cushion, their limit for this person − what's
out, their total cap − everything they've committed)`, rounded down; no automatic help unless their forecast
is *confident*. `allocate()` covers a need with the fewest supporters, deterministically. Pinned on the real
engine for every demo day in `tests/test_demo_scenario.py`.

**Money integrity** (`backend/app/safety_net.py`, `app/reconcile.py`): every transfer is journaled before
Nessie is called and tagged in both memos; an unclear outcome (timeout, 5xx) is **never retried** — it is
reconciled by finding the tag in Nessie, and absence is never treated as "nothing moved". Per-person
Postgres advisory locks + a unique index stop two passes from spending the same supporter twice.

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
| **Agent** (live Gemini, 58 questions across 3 voices: afford / fix it / subscriptions / forecast / safety net / peer-to-peer / needs vs. could-wait) | **100%** tool selection · **97%** correct answers · **100%** of $ figures traceable to the engine · 0 API errors |
| **Agent, offline baseline** (58 questions incl. peer-to-peer, safety net, weekly brief, needs vs. could-wait) | 100% / 100% / 100% |
| **Forecast backtest** (learn months 1–3, predict month 4, 18 folds) | daily balance error **$138**: −66% vs ignoring everyday spending, −16% vs repeating last month |
| **Learning curve** (only 30 days of history) | error **$2,737 → $206** with provisional paydays |
| **Range calibration** (cautious end beaten, target 5%) | **12–43% → 4–11%** on held-out IBM card users and a real UK account it never trained on |
| **Tone** (Gen Z voice stays itself when money is tight or fine; rule-based checks on real Gemini replies) | **3/6 → 6/6** (Gen Z cells) · re-run after the privacy prompt: **17/18** across all voices |
| **Latency** (Ask Runway on live Gemini, 4 questions × 2 runs) | **~13 s → ~6 s** a reply with low thinking; agent 98%, privacy 15/15 guard off |
| **Privacy** (13 attacks incl. prompt injection + 2 controls; fails on any of the other person's real figures) | **15/15** guard + router · **15/15** guard + Gemini · **15/15 Gemini with the guard OFF** |
| **Demo scenario** (Guardian on the real engine, Oct 18–22) | Maya $135 → Sam $90 + Emma $45, Jordan $0, every day |
| **Several short at once** (Maya + Alex share Sam's $90; fewest-options-first) | Maya fully covered · Alex $50 of $85 · **$185 covered vs $135 first-come**, every demo day |
| **Guardian invariants** (2,000 generated networks: limit, exposure, cushion, overshoot, confidence, determinism) | **0 violations** · 1,160 authorized-but-unsafe transfers blocked · mutants caught (163 / 663) |

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
- **Consent is two-sided and never inferred.** Old limits were migrated in with *no* consent; automatic help
  needs the supporter's and the recipient's explicit yes (audited). Over a limit, the supporter approves —
  in the app, or on their phone via Auth0 push (CIBA) when that's configured.
- **Protect the protector.** A big balance today isn't safety: capacity comes from the supporter's cautious
  forecast for the whole time the money is out, so a bill next week shrinks what Runway will move.
- **Privacy at the server, not the screen.** A supporter's API responses never contain the recipient's
  balance, spending, forecast or reason; tests call the real routes with real tokens to prove it.
- **Never pretend a transfer worked.** Partial success is recorded as partial; unclear results wait for
  reconciliation instead of a retry that could pay twice. A prototype on a sandbox — not production banking.
- **Sandbox limits, said out loud.** In production, ownership comes from the bank's own login and each
  customer grants their own token. In Nessie, one API key lives only on the server and every money move
  checks the signed-in owner first. Only the data connector is bank-specific.

## Built with

| | Used for |
|---|---|
| **Capital One Nessie** | the bank: customers, accounts, merchants, purchases, deposits, bills, transfers; every money move is a real Nessie record ([`docs/NESSIE.md`](docs/NESSIE.md)) |
| **Gemini** (`gemini-3.8-flash`) | the assistant: tool calling over the forecast engine |
| **Auth0** | sign-in on web and phone, owner-only money moves; CIBA push approvals built (in-app approval when push isn't configured) |
| **Tiger Data** (TimescaleDB) | transactions and saved forecasts as hypertables; continuous aggregates for daily spend and forecast accuracy; agreements, audit trail and the transfer journal |
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

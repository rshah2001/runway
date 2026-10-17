# Hackathon plan

## The pitch (30 seconds)

Banking apps tell you what already happened. Runway tells you what's about to happen: a day-by-day
balance forecast, the exact day you'd go under, and an AI banker that fixes it with real money
movement — after you approve it. Overdraft fees cost Americans billions a year; this is the app
that sees them coming.

## Prize targets

| Prize | How we qualify | Effort |
|---|---|---|
| **Capital One — Best Use of Nessie** ($250/person) | Nessie is the data source *and* the action layer: accounts, merchants, bills **and peer-to-peer** (real transfers + deposits between real Nessie customers) | Core |
| **Overall — Hack of the Year** | Real problem, live demo, technical depth | Core |
| **AI track (Most Creative Use of AI)** | Tool-calling agent + forecasting model + evals + clean public README | Core |
| **Best Use of Gemini** (MLH) | Gemini powers the agent | Free |
| **Best Use of Auth0** (MLH) | Login + **Auth0 for AI Agents**: the safety-net agent acts for one person with another's pre-agreed limit, and asks the lender by **Auth0 push (CIBA)** when it's over | Medium |
| **Best Use of Tiger Data** (MLH) | Transactions as a hypertable; continuous aggregates feed forecast + charts | Medium |
| **Best Use of Vultr** (MLH) | Backend + DB hosted on Vultr | Low |
| **GoDaddy Registry domain** (MLH) | Register a domain for the deployed app | 10 min |
| **Easy On The Eyes** | One person owns UI polish the whole time | Ongoing |
| **DEV Writing Challenge** | Write-up after the event | Post-event |

**Skipping:** DeepSpace (overlaps Auth0), Solana, Hardware, Sperry (different problem), Least Vibe Coded.
**TODO:** check the Devpost rules for a cap on how many tracks one project can enter.

**AI-track note:** the AI judges will read the code. They value depth over polish, clean documented
code, and being able to explain design choices and tradeoffs. Keep commits clean and the README honest.

## Core design decision — say this to the AI judges

**The LLM never does math.** Gemini decides *which tool to call* and explains the result. Every number
comes from the deterministic forecast engine. That kills hallucinated balances and makes the agent
testable — which is exactly what our evals measure.

## AI depth

1. **Forecast engine** — baseline: scheduled bills + detected payday rhythm, projected forward.
   Upgrade: per-category spend model learned from purchase history (day-of-week seasonality).
2. **Recurring-transaction detector** — cluster purchases by merchant, find stable interval + amount.
   Powers the "subscription detective."
3. **Evals** (results table goes in the README):
   - *Forecast backtest:* train on months 1–3 of seeded history, predict month 4, report MAE/MAPE.
   - *Agent eval:* 30–50 "Can I afford X on day Y?" questions with ground truth from the engine.
     Measure tool-selection accuracy and final-answer accuracy.

## Demo script (~3 min)

1. Log in (Auth0) as **Maya, 20**. Her chart dips under the $300 floor before Friday's payday.
2. **Family safety net** (the headline — `docs/SAFETY_NET.md`): nobody asks. Runway sees the dip,
   checks that grandpa **Sam (60)** can help safely, and moves **$100** within the limit *he* set —
   real Nessie money. Maya's chart turns green: *"Sam covered you — it goes back on payday."*
3. Over the limit: lower Sam's limit to $50, Maya needs $100 → **Sam's phone buzzes (Auth0 push)**,
   he approves on stage, money moves.
4. Switch to Sam: the timeline shows *"comes back Fri"* → on payday *"💸 You got your $100 back."*
5. "Can I go to the concert Friday? $180." → *"Not safely."* · Peer-to-peer: *"Alex still owes you $45"*
   → settle → real transfer between two Nessie customers.
6. Close on the guardrails slide (lender sets the limit, it must come back by payday, helping must be
   safe for the helper) + eval numbers + architecture.

## Team split

One Expo codebase ships the **website, iOS app and Android app**. Full file ownership in `docs/TEAM.md`.

| | Owns |
|---|---|
| **rshah2001 + Claude — A: Data + backend** | Nessie client + seed personas, Tiger Data schema + aggregates, FastAPI, Vultr deploy + CI/CD, domain |
| **an2thu — D: App UI + design** | Every screen (Today, Ask, Spending, login), runway chart, chat + approval cards, polish, slides, demo video |
| **Patil-Hemangi — B + C: AI + auth** | Forecast engine + ML, recurring detector, Gemini agent, evals, Auth0 login + approval before money moves |

## Timeline (adjust to the event's hours)

| Hours | Milestone |
|---|---|
| 0–2 | Domain, Vultr credits, Auth0 tenant, Tiger Data instance, Nessie key. Agree the API contract in `ARCHITECTURE.md`. |
| 2–8 | Seed script → Tiger Data ingest → baseline forecast endpoint. UI skeleton with live chart. |
| 8–16 | Gemini agent + tools. Auth0 approval before money moves. Recurring detector. |
| 16–22 | Evals. ML upgrade. UI polish. Deploy to Vultr on the custom domain. |
| 22–end | **Feature freeze.** README, backup demo video, pitch, Devpost (name sponsor features per prize). |

## Risks → fallbacks

- **Nessie slow/down** → every read is cached in Tiger Data; demo runs from cache, only the "fix it" write is live.
- **Auth0 async approval eats too much time** → in-app confirm modal; keep Auth0 for login so we still qualify.
- **Live demo breaks** → pre-recorded video.

## Reusing the prototype

`prototype/index.html` already has, working: the day-by-day projection (`buildEvents` + `project`),
the runway chart (`chartSVG`), the "Can I buy it?" verdict (`verdictFor`), the rule-based coach
(`coachAdvice`), spending tabs, IOUs and debts. Port the logic to the backend and the look to the
frontend — don't rewrite what already works.

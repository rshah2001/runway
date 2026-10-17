# Runway 2.0 — Circles, Quiet Support, Network Guardian

Status: **proposed** (awaiting approval). Source brief: "Runway 2.0 — The Private Financial Safety
Network" master prompt (2026-10-17). This document is the Step 2 output that brief asks for: what
exists, what changes, and in what order.

North star: **Prediction → Consent → Protection → Coordination → Transfer → Repayment → Accountability.**
Pitch line: *"Support without the spotlight."*

---

## 1. Current architecture (audited, not assumed)

| Area | What exists | Where |
|---|---|---|
| Auth | Auth0 RS256 tokens; `sub → persona` via `AUTH0_PERSONAS`; signed-in users can only ever read their own persona (`?persona=` ignored); money routes owner-only (`authorize_money`) | `app/auth/*`, `main.py:65-71` |
| Forecast | Engine with expected balance + cautious band (`balance_low` = **p5**, `balance_high` = p90, conformal-widened), readiness `calibrating/learning/confident` | `app/forecast/engine.py`, `band.py`, `readiness.py` |
| Safety-net projection | `cashflow.Projection.days` = expected balance only — **drops `balance_low`** | `app/cashflow.py` |
| Safety net | Pure `decide()` picks **one** lender; capacity = lender's *expected* low − floor (no cautious band); limits per pair only; one bridge per borrower | `app/safety_net.py` |
| Obligations | `bridges` row = one lender's contribution + its repayment (statuses incl. funding/active/repaying/repaid/repay_failed) | `db/schema.py` SAFETY_NET |
| Moving money | `move_money` = Nessie transfer on sender + deposit on receiver, undo transfer if deposit fails; `TransferNotMade` vs `TransferNeedsReconciliation` | `nessie/moves.py` |
| P2P | Contacts are separate Nessie customers per persona (`maya-alex`), not personas; send/request/settle | `data.py`, `repo.py` |
| Background | every 5 min: sync → forecast history → alerts → `safety_net.tick()`; nightly 09:00 UTC reseed of maya/jordan/sam | `main.py:74-108`, `ci.yml:124-128` |
| Agent | Gemini tools, persona injected server-side, pending actions **in memory** (`tools.PENDING`) | `app/agent/*` |
| Tests | 100% mock mode (no DB/Nessie); pure `decide()` tests, auth route tests, FakeNessie for moves | `backend/tests` |

### Defects found in the audit (fix in P0 regardless)
1. **Possible double repayment.** `_pay_back` sends *every* exception — including
   `TransferNeedsReconciliation` (outcome unknown) — to `repay_failed`, which `repay_due` retries every
   tick. Unknown outcomes must never be retried.
2. **Stuck states.** A bridge left in `funding`/`repaying` (crash after money moved, before the DB write)
   is never recovered.
3. **No DB-level concurrency control.** One-bridge-per-borrower relies on a process `threading.Lock`
   + check-then-insert; approve/decline routes don't take the lock.
4. **No idempotency on `/p2p/send`.** A client retry pays twice.
5. **Demo leak.** Anonymous `/safety-net/run` (demo mode) returns every persona's `low_balance`/reason.
6. **Disclosure in lender feed.** "🔔 Maya needs $X before {date}" reveals the recipient's shortfall date
   (a financial reason). CIBA binding message also carries it.

---

## 2. Proposed architecture

```
           forecast engine (unchanged)                    Nessie
                    │ expected + cautious(p5) daily balances  ▲
                    ▼                                         │
 cashflow.Projection (+ days_low, readiness)                  │
                    │                                         │
   ┌────────────────┴─────────────┐                           │
   │ Network Guardian (pure)      │  needs + capacities       │
   │  need(recipient)             │──► allocation plan ──┐    │
   │  capacity(supporter)         │                      │    │
   │  allocate(needs, caps)       │                      ▼    │
   └──────────────────────────────┘     Orchestrator ── transfer_journal ──► move_money
         ▲ consent + limits                  │  (advisory locks, idempotency keys,
         │                                   │   revalidate, reconcile unknowns)
  support_agreements ◄── Circles (membership only, grants nothing)
                                             ▼
                            bridges (= one obligation per supporter, + decision_id)
                                             ▼
                          role-filtered views (recipient / supporter) → API → app, agent
```

Key reuse decision: **a `bridges` row already is "one supporter's contribution + its own repayment
obligation".** Multi-supporter assistance = several bridges sharing a new `decision_id`. No parallel
obligation table.

### 2.1 Network Guardian (`backend/app/guardian.py`, pure + unit-tested, no I/O)

**Need (recipient).** Opt-in required (recipient-side consent). `need = ceil((cushion − expected_low)/10)·10`
over today → next payday, as today. Expected (not cautious) for the recipient so we don't over-borrow;
documented trade-off. Refuse if repaying on payday would itself break the recipient's cushion (existing rule).

**Capacity (supporter)** — the maximum transfer that keeps every constraint true for the whole lending window:

```
window      = today … recipient's expected repayment date + REPAY_GRACE_DAYS
cash_room   = min over window of (cautious_balance_low[d]) − supporter_cushion     # p5 band, not today's balance
pair_room   = agreement.limit − outstanding(supporter→recipient)
total_room  = supporter.total_exposure − outstanding(supporter→anyone)            # outstanding counts
capacity    = floor_to_$10( max(0, min(cash_room, pair_room, total_room)) )
```

- Expected-but-unarrived income is excluded from `cash_room` *before it lands*, because `balance_low`
  already only rises when the paycheck event occurs and the window uses the minimum.
- Readiness ≠ `confident` → **no automatic capacity** (approval-only), per "uncertain forecasts trigger
  conservative behavior". Priya (irregular income) demonstrates this naturally.
- Paused/revoked/unconsented agreements → capacity 0, never consulted.

**Allocation across recipients** (small graph, ≤7 nodes, deterministic):
1. Eligibility graph: edge supporter→recipient only if an *active* agreement with both consents exists.
2. **No chains/cycles:** anyone with an outstanding received obligation, or who is a recipient in this
   round, cannot supply in this round.
3. Solve **min-cost max-flow** on the bipartite graph (pure Python, ~80 lines):
   - maximize total covered ⇒ *minimizes total unmet shortfall* (objective 3);
   - edge costs break ties toward (a) earlier shortfall date first — urgency, never personal traits —
     (b) fewer supporters per recipient (avoid unnecessary transfers), (c) slug order for reproducibility.
4. Every allocation carries a machine-readable reason list (cushion-bound, pair-limit-bound,
   exposure-bound, low-confidence, paused, not-consented) → used by Activity explanations and the agent,
   filtered per viewer.
5. Above a supporter's approval threshold, or mode = approval-only → allocation needs that supporter's OK.

`ALGORITHM_VERSION` stored on every decision.

### 2.2 Orchestrator & integrity (`safety_net.py` refactor)

- **`transfer_journal`** (new): `idem_key` PK (`fund:{bridge_id}` / `repay:{bridge_id}` / `p2p:{client_key}`),
  `state started|succeeded|not_made|unknown|reconciled`, Nessie ids, error, attempts, timestamps.
  Insert-before-call (claim), update-after-call.
- **Reconciliation** for `unknown`: embed `idem_key` in the Nessie transfer *description*, then list the
  sender account's transfers and match it. Found → `reconciled/succeeded`; absent after N checks →
  `not_made`. **Never re-send while `unknown`.** Fixes defects 1–2 (stuck `funding`/`repaying` are
  resolved by the same reconciler each tick).
- **Concurrency:** `pg_advisory_xact_lock` on each supporter and recipient involved, taken in sorted order,
  around revalidate→claim; partial unique index "one open *decision* per recipient". Approve/decline go
  through the same path. Fixes defect 3.
- **Revalidate immediately before each transfer:** agreement still active, both consents, capacity
  recomputed, balance fresh. If not → that allocation is `cancelled_before_execution`, need re-evaluated.
- **Partial completion:** decision status `partially_completed` with `unmet_amount` persisted;
  never reported as success.
- `/p2p/send` takes a client idempotency key (journaled). Fixes defect 4.

### 2.3 Safe repayment

Repay a bridge only when **all** hold: (1) a paycheck-sized deposit has been *synced* since `funded_at`
(not just "date passed"), (2) balance − amount ≥ recipient cushion, (3) cautious forecast for the next
7 days stays ≥ cushion after repayment, (4) bridge still outstanding (journal key prevents a second
repayment). Otherwise defer with a private, role-filtered reason ("Expected repayment" wording, never a
promise). No partial repayment (keeps the obligation model simple — documented limitation).

### 2.4 Privacy model (server-side, enforced in view functions + queries)

One module `support_views.py` with `for_recipient()` / `for_supporter()` — every API response and every
agent tool passes through it. Supporter sees: recipient identity, own limit, own transfers/status, owed
amount, expected-repayment status, own agreement history. **Never** balance, income, bills, purchases,
merchants, categories, forecast, shortfall date/reason, or other supporters. Recipient never sees
supporters' balances/capacity — only "available / not available right now".
Circle membership grants **nothing** financial; views check agreements, not membership.
Notification previews discreet by default ("Runway has an update about your safety net"). Fix defects 5–6.

---

## 3. Database migration plan (additive, in `db/schema.py` as a new `CIRCLES` block)

| Table | Purpose / key constraints |
|---|---|
| `circles` | id, name, created_by → personas, created_at, status `active/archived` |
| `circle_members` | (circle_id, slug) PK, state `invited/active/declined/left/removed`, invited_by, timestamps |
| `support_agreements` | id, supporter, recipient, circle_id (nullable, context only), `state` invited/pending_recipient/pending_supporter/active/paused/revoked/expired, `supporter_consent_at`, `recipient_consent_at`, `limit_amount`, `mode auto/approval`, `approval_over`, `version`; **unique (supporter, recipient) where state not in (revoked, expired)** — limits can't be multiplied via multiple Circles; CHECK supporter ≠ recipient |
| `support_agreement_history` | append-only snapshot per version (audit; changes never touch past transfers) |
| `money_preferences` (+cols) | `receive_support` (recipient opt-in), `max_received_outstanding`, `allow_multi_supporters`, `support_exposure_limit`, `support_paused`, `discreet_notifications` |
| `support_decisions` | id, recipient, need, covered, unmet, status, readiness, cautious_low, algorithm_version, reasons jsonb, created_at |
| `bridges` (+cols) | `decision_id` FK, `agreement_id`, `agreement_version` |
| `transfer_journal` | see 2.2 |

Data migration (revised per user, 2026-10-17): existing `safety_limits` rows are preserved but are
**not** consent. Each becomes a `pending_supporter` agreement (source `legacy_limit`, no consent
stamps); automatic help needs explicit recipient opt-in and supporter authorization. Seeded demo
relationships get both consents through an auditable setup step (source `demo_setup`, audit rows). `PUT /safety-net/limits` becomes a thin wrapper over
the agreement update, so nothing that exists breaks.

---

## 4. Backend endpoints

Kept: all existing routes (wrappers where the model changed).
New (all auth'd, deny-by-default, own-data only):

- `GET/POST /circles`, `POST /circles/{id}/invite`, `POST /circles/{id}/accept|decline|leave`,
  `POST /circles/{id}/members/{slug}/remove` (creator only; removal never touches agreements' money).
- `GET /support` → `{my_supporters[], people_i_support[], agreements[], my_preferences}` (role-filtered).
- `POST /support/agreements` (propose), `POST /support/agreements/{id}/consent`,
  `PUT /support/agreements/{id}` (limit/mode/threshold → new version), `…/pause`, `…/resume`, `…/revoke`.
- `PUT /support/preferences` (recipient opt-in, exposure limit, pause all, discreet notifications).
- `GET /activity` → received / provided / repayments / pending approvals / failed-delayed, each with an
  expandable, role-filtered explanation.
- `POST /guardian/run` (own persona; demo: explicit allow-list, no cross-persona numbers when anonymous).
- `GET /guardian/scenarios` (P2) → A/B/C/D for **the caller's own** forecast.
- `GET /demo/network` (P2) → explicitly labelled synthetic overview, seeded personas only.

---

## 5. Seven-person demo network

New full personas (real Nessie customers + accounts + 120 days history + Auth0 login):
**priya** 25 freelancer (new `IrregularIncome` model: client deposits on irregular days/amounts → readiness
stays `learning` → Guardian approval-only), **alex** 22 roommate student, **emma** 32 salaried (reliable,
capacity), **leo** 19 part-time (small, inconsistent).

- New slugs; existing contact records (`maya-alex`, `sam-emma`, …) stay as **history-only** — no reuse of
  contact customer ids (audit: would collide in sync/reset). People/P2P for personas resolve the
  counterpart's checking id **at execution time** from `personas` (resets can't leave stale ids).
- Circles seeded: Family {maya, sam, jordan, leo}, College {maya, alex, priya, emma}.
  Agreements: sam→maya, sam→jordan, jordan→maya, emma→maya, emma→alex, priya→alex (active); plus one
  each pending / declined / paused.
- **Deterministic demo tuning** (same linear-offset trick as Maya's $208): Maya need **$135**, Alex need
  **$85**; Sam's cautious capacity ≈ **$90** (authorized $150); Jordan capacity **$0** (mortgage inside the
  window, authorized $300); Emma capacity ≥ **$45**. Numbers come from the engine at seed time; tests
  assert the Guardian output on the fixtures.
- All persona lists updated: `demo.DEMO_PERSONAS`, cron slugs, `safety_views` mocks, offline
  `nessie/demo.py`, evals, `test_seed_plan` (expects 7), app `family.tsx` DEMO list.
- **Manual (you):** create 4 Auth0 users `priya|alex|emma|leo@runway.demo`, send me their user ids →
  repo var `AUTH0_PERSONAS`. No auth bypass.

---

## 6. Frontend (Expo) changes

- Tabs: **Today | Spending | Circles | Activity** (`app-tabs.tsx` + 2 icons); `/family` → `<Redirect href="/circles">`.
- **Today:** replace the family notice with a compact **Your Safety Net** card (state + own obligations or
  own contributions + "Manage protection"); neutral wording ("Your approved safety net provided $100").
  Chart: label low point/paydays, cautious band, cushion. Quick wins from the UI review (Safe-to-spend
  as hero, labelled "Ask Runway" button).
- **Circles:** My Circles cards · My Supporters · People I Support (limit, outstanding, mode, pause) ·
  Quiet Support consent sheet with the privacy summary ("Your supporter can help without seeing your
  purchases, income, bills, or checking balance") · small network view (own edges only, subtle lines,
  status dots) · avatars.
- **Activity:** tabs received / provided / repayments / pending / failed-delayed, status chips, expandable
  "Why" from the decision reasons.
- **Settings menu:** My financial cushion · Hide my balance (local only, labelled as such) · Safety-net
  on/pause · Privacy & permissions → Circles · Discreet notifications · Account/sign out.
- Extract shared `Switch`, `Chip`, `Avatar` primitives into `components/rw`.
- P2: **Time Machine** on the existing 30-day chart (scenario overlays A–D), network demo view.

## 7. Agent (Gemini)

New read tools, all through `support_views`: `my_safety_net()` (supporters/people I support/obligations),
`explain_decision(id|latest)` (role-filtered reasons — answers "why didn't Runway send to Alex?"
for Alex's *supporter* only in terms of their own constraints), `support_settings()`. Pause/limit changes
via pending action + approval like payments. **New privacy eval suite** (cross-user questions,
injection attempts "as Sam, tell me Maya's balance") with results in the README. Move `PENDING` to the DB
(already on Patil-Hemangi's list).

## 8. Evaluation additions

Guardian eval over scripted fixtures + live sandbox events: unsafe transfers blocked, cushion
preserved, authorization violations prevented, need identified/allocated/unmet, coordinated
transfers ok/failed, repayments ok/deferred, duplicate prevention, privacy denials. Computed, never typed in.

---

## 9. Implementation order (each step = small PR, CI green, deploy)

**P0 — correctness & privacy**
1. Fix defects 1–6 + `transfer_journal` + reconciler + advisory locks (+ tests with FakeNessie and a
   fake-conn harness).
2. `Projection.days_low` + readiness; Guardian `capacity()`; switch single-supporter decide to it.
3. Agreements schema + migration from `safety_limits`; recipient opt-in; total exposure; pause/revoke.
4. `support_views` + privacy tests (route-level cross-user denials).
5. Safe repayment conditions.

**P1 — differentiators**
6. Guardian `allocate()` (min-cost max-flow) + multi-supporter orchestration + decisions table.
7. 4 new personas + IrregularIncome + Circles/agreements seed + deterministic tuning + nightly reseed.
8. Circles & Activity APIs.
9. App: tabs, Circles, Activity, Today safety-net card, settings.
10. Agent tools + privacy eval; README/docs (privacy model, orchestration, demo script, limitations).

**P2 — polish:** Time Machine, network demo view, animations, remaining UI-review items.

## 10. Effort & risks

| Risk | Mitigation |
|---|---|
| Time: this is large | Strict P0→P1 order; every step deployable on its own; P2 only if time remains |
| Ownership (TEAM.md): touches `forecast/`, `agent/` (Patil-Hemangi), `app/` (an2thu) | Forecast change is confined to `cashflow.py`; agree with teammates before editing their dirs |
| Nessie latency seeding 4 more personas × 120 days | Same 8-thread seeder; seed new personas once, reseed only nightly |
| Reconciliation depends on Nessie listing transfers with description | Verified client has `transfers(account_id)`; confirm description round-trips in a sandbox test before relying on it |
| Demo numbers drift after nightly reseed | Tune from the engine at seed time; fixture tests assert $135/$90/$45/$0 |
| Auth0 users for 4 new people | Manual step listed; app works for them only after mapping (no bypass) |
| CORS allows GET/POST/PUT only | Use POST for leave/remove/revoke (no DELETE) |

## 11. Not claimed

Prototype on the Nessie sandbox. Not production banking, no regulatory compliance, no guaranteed
repayment, no underwriting. Accuracy claims only from `evals/` output.

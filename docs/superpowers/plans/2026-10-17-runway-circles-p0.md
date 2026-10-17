# Runway Circles — Deadline Implementation Plan (submissions close Oct 18, 8:00 AM EDT)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (native). Steps use `- [ ]`.
> UI tasks: load the `apple-design` skill first (user request).

**Goal:** Make the money path provably safe, add two-sided consent and a deterministic Network Guardian,
rename Family → Circles, and ship a reproducible demo: Maya short $135 → Sam $90 + Emma $45, Jordan
blocked, verified Nessie transfers, privacy boundary shown.

**Architecture:** Extend `app/safety_net.py` (bridges = one obligation per supporter) with a
`transfer_journal` + reconciler, Postgres advisory locks, `support_agreements` with explicit consents,
and a pure `app/guardian.py` that sizes each supporter's safe contribution from the existing p5 band.

**Tech Stack:** FastAPI, psycopg 3, Tiger Data (Postgres/Timescale), Nessie, Expo Router.

**Spec:** `docs/superpowers/specs/2026-10-17-runway-circles-design.md` + user's approval message
(2026-10-17): consent migration must NOT infer consent; Emma optional; Time Machine/7 users/Gemini
extras deferred.

## Global Constraints

- Never retry a money move whose outcome is unknown; resolve via reconciliation or mark `reconcile`.
- Every Nessie move carries a tag `[rw:<key>]` in both memos; keys are unique per logical move.
- Existing `safety_limits` rows are preserved but never count as consent.
- Automatic assistance requires: agreement `active` (supporter_consent_at AND recipient_consent_at set,
  neither from `legacy_limit`), recipient `family_cover` on, not paused, readiness `confident`.
- The LLM never computes or authorizes money. All amounts from `guardian.py`/engine.
- Supporter-facing text never contains the recipient's balance, shortfall date, or reason.
- Run before every commit: `cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/pytest -q`.
- One PR per task group; merge only with CI green (merging deploys).

## Review Focus

1. A reconciler tick that runs while a move is still in flight → must not mark it `not_made`
   (only journal rows older than 2 minutes are reconciled).
2. Approve tapped twice / approve racing the background tick → exactly one funding.
3. Supporter changes limit or revokes between allocation and execution → revalidate cancels it.
4. Nightly reseed while a bridge is `reconcile` → reseed deletes accounts; bridges for reset personas
   are forgotten first (existing `safety_repo.forget`) — keep that order.
5. Anonymous demo visitor hits `/safety-net/run` → sees only the demo persona's own decision.

---

### Task 1: Tagged moves + transfer journal + reconciler

**Files:** Modify `app/nessie/moves.py`; Create `app/db/journal_repo.py`, `app/reconcile.py`;
Modify `app/db/schema.py` (new `JOURNAL` block, add to `apply()`); Test `tests/test_moves.py`,
`tests/test_reconcile.py`.

**Interfaces — Produces:**
- `move_money(nessie, from_account, to_account, amount, on, memo, deposit_memo, *, key: str | None = None)`
  → unchanged return; when `key` is set both memos end with ` [rw:{key}]`.
- `find_move(nessie, from_account, to_account, key) -> tuple[str | None, str | None]` (transfer id,
  deposit id) by scanning `nessie.transfers(from)` / `nessie.deposits(to)` for the tag.
- Schema `transfer_journal(key text PK, kind text CHECK in ('fund','repay','p2p'), ref text, from_account,
  to_account, amount numeric(12,2) CHECK >0, state text CHECK in ('started','succeeded','not_made','unknown',
  'reconcile'), transfer_id, deposit_id, error text, checks int DEFAULT 0, created_at, updated_at)`.
- `journal_repo.claim(conn, key, kind, ref, from_account, to_account, amount) -> bool` (INSERT … ON
  CONFLICT DO NOTHING; False = already exists), `finish(conn, key, state, transfer_id=None, deposit_id=None,
  error=None)`, `get(conn, key)`, `unresolved(conn, older_than: timedelta) -> list[Row]` (state in
  started/unknown).
- `reconcile.resolve(nessie, row) -> Literal['succeeded','not_made','reconcile']`:
  both legs found → succeeded; transfer only → `delete_transfer` then not_made (delete fails → reconcile);
  deposit only → reconcile; neither → not_made only if `row.checks >= 1` (second look), else stays unknown
  (increment checks).

- [ ] Tests (FakeNessie gains `transfers()/deposits()` lists): `test_key_tags_both_memos`,
  `test_find_move_matches_tag_only`, `test_resolve_both_legs_succeeded`,
  `test_resolve_transfer_only_is_undone_and_not_made`, `test_resolve_neither_needs_two_looks`,
  `test_resolve_deposit_only_needs_human`.
- [ ] Implement; run pytest; commit `Money moves: tagged memos, transfer journal, reconciler`.

### Task 2: Safety-net state machine on the journal (defects 1, 2)

**Files:** Modify `app/safety_net.py` (`_fund`, `_pay_back`, `tick`, new `reconcile_pending`), `app/db/schema.py`
(bridges status CHECK gains `'reconcile'` via `ALTER TABLE bridges DROP CONSTRAINT IF EXISTS bridges_status_check;
ALTER TABLE bridges ADD CONSTRAINT bridges_status_check CHECK (...)`), `app/db/safety_repo.py`
(`OUTSTANDING` += `'reconcile'`); Test `tests/test_safety_flow.py` (new, in-memory fake conn + FakeNessie,
monkeypatch `pool.connection`).

Rules:
- Journal keys: `fund:{bridge_id}`, `repay:{bridge_id}`. Claim before calling `move_money(key=…)`.
- `TransferNotMade` → fund: `failed`; repay: `repay_failed` (retry allowed).
  `TransferNeedsReconciliation` / any other exception → bridge `reconcile`, journal `unknown`. Never retried.
- `reconcile_pending()` (first step of `tick`): for journal rows unresolved > 2 min, `resolve()`; map
  succeeded → bridge `active`/`repaid` (with ids), not_made → `failed`/`repay_failed`, reconcile → bridge
  `reconcile` + one event "We're confirming this with the bank". Also bridges stuck in `funding`/`repaying`
  > 10 min with no journal row → `failed`/`active` (nothing was sent: claim precedes send).
- `repay_due` never selects `reconcile`.

- [ ] Tests: `test_repay_unknown_outcome_is_never_retried`, `test_repay_not_made_is_retried`,
  `test_fund_unknown_then_found_becomes_active`, `test_stuck_funding_without_journal_is_failed`.
- [ ] Implement; pytest; commit `Safety net: unknown outcomes reconcile, never retry`.

### Task 3: Concurrency (defect 3)

**Files:** `app/db/safety_repo.py` (`lock_people(conn, *slugs)` → `pg_advisory_xact_lock(hashtext('runway:'||s))`
in sorted order), `app/safety_net.py` (`act`, `_fund` claim, `decline` take locks on lender+borrower before
the compare-and-set), schema: `CREATE UNIQUE INDEX IF NOT EXISTS bridges_one_open_pair ON bridges
(borrower_slug, lender_slug) WHERE status IN ('pending_approval','funding','active','repaying','repay_failed','reconcile')`.

- [ ] Test (unit, fake conn records SQL): `test_act_locks_people_in_sorted_order`.
- [ ] Implement; pytest; commit.

### Task 4: Idempotent Send money (defect 4)

**Files:** `app/schemas.py` (`P2PSend.client_key: str | None = Field(None, pattern=r"^[A-Za-z0-9-]{8,64}$")`),
`app/lib/types.ts` mirror, `app/data.py` (`p2p_send`: journal key `p2p:{persona}:{client_key}`; existing
succeeded row → return the recorded payment, no move), `app/src/lib/api.ts` (`p2pSend` sends a fresh
`crypto.randomUUID()` per confirmed tap; the button disables while in flight).

- [ ] Test `tests/test_p2p_idempotency.py::test_same_client_key_pays_once` (FakeNessie, writes on).
- [ ] Implement; pytest; commit.

### Task 5: Privacy leaks (defects 5, 6)

**Files:** `app/main.py` (`/safety-net/run`: anonymous → only `PERSONA` default/`?persona=` single persona,
never all), `app/safety_net.py` supporter-facing strings (no shortfall date / balance / reason; e.g.
"🔔 Maya asked for $100 of support (over your auto limit). Approve in Runway — expected back Fri Oct 23."),
CIBA binding message `Approve {amt} support for {name}`.

- [ ] Tests: `test_anonymous_run_returns_one_persona`, `test_supporter_messages_have_no_shortfall_date`
  (scan every `_both(..., to_lender)` string built by `act`/`_fund` for the shortfall date).
- [ ] Implement; pytest; **PR #A (Tasks 1–5), CI, merge, verify `/api/health`.**

### Task 6: Support agreements with explicit two-sided consent

**Files:** schema `AGREEMENTS` block; Create `app/db/agreements_repo.py`, `app/agreements.py`; `app/main.py`
routes; `app/schemas.py` + `types.ts`; Test `tests/test_agreements.py`.

- Table `support_agreements(id text PK, supporter text FK personas, recipient text FK personas, limit_amount
  numeric(12,2) CHECK 0..1000, mode text CHECK in ('auto','approval') DEFAULT 'auto', state text CHECK in
  ('pending_recipient','pending_supporter','active','paused','revoked'), supporter_consent_at timestamptz,
  supporter_consent_source text, recipient_consent_at timestamptz, recipient_consent_source text,
  version int DEFAULT 1, created_at, updated_at, CHECK supporter<>recipient)`;
  `UNIQUE (supporter, recipient) WHERE state <> 'revoked'`.
- `support_agreement_events(id bigserial, agreement_id, actor text, action text, detail jsonb, at)` — audit.
- `money_preferences` += `support_exposure_limit numeric(12,2)` (NULL = 500 default).
- Migration (idempotent, in `agreements.migrate_legacy(conn)` called from seed/startup): each
  `safety_limits` row without an agreement → `pending_supporter` (source `legacy_limit`, NO consent stamps),
  audit `migrated`. `safety_limits` untouched.
- `agreements.propose(conn, actor, other, role, limit)`, `consent(conn, actor, id)`, `set_limit(conn, actor,
  id, limit)` (supporter only; bumps version; audit), `pause/resume/revoke(conn, actor, id)`.
  Only the right party can act (403 otherwise). Active iff both consents present.
- Routes: `GET /support`, `POST /support/agreements`, `POST /support/agreements/{id}/{consent|pause|resume|revoke}`,
  `PUT /support/agreements/{id}/limit`, `PUT /support/preferences` (exposure limit). `PUT /safety-net/limits`
  → wrapper over supporter `set_limit`/`propose`.
- `safety_net.plan()` helpers come from active agreements only.
- Demo setup: `seed.agreements.setup_demo(conn)` records both consents with source `demo_setup` + audit rows.

- [ ] Tests: `test_legacy_limit_is_not_consent`, `test_both_consents_make_active`,
  `test_only_supporter_sets_limit`, `test_revoked_agreement_gives_no_helper`, `test_limit_change_bumps_version`.

### Task 7: Network Guardian MVP (pure)

**Files:** `app/cashflow.py` (`Projection.days_low: list[tuple[date, Decimal]]`, `readiness: str`), Create
`app/guardian.py`; `app/safety_net.py` `decide()` → uses guardian; Test `tests/test_guardian.py`.

- `capacity(p: Projection, *, start, end, pair_remaining, exposure_remaining, confident: bool) -> Capacity`
  `(amount: Decimal, bound: Literal['cushion','pair_limit','exposure','low_confidence','none'])`:
  `cash = min(days_low in [start,end]) - p.floor`; `amount = floor_to_10(max(0, min(cash, pair, exposure)))`;
  not confident → amount 0, bound `low_confidence` (approval route).
- `allocate(need, caps: list[(slug, Capacity)]) -> list[(slug, Decimal)]`: largest capacity first, fewest
  supporters, deterministic tiebreak by slug; returns partial if insufficient.
- Recipient repayment safety: cautious (`days_low`) balance over `payday … payday+7` minus total need
  ≥ recipient floor, else `no_safe_helper` ("repaying would cause another shortfall").
- Window end = recipient payday + `REPAY_GRACE_DAYS`.
- Decision gains `allocations: list[tuple[str, Decimal]]` and `decision_id`; `act()` inserts one bridge
  per allocation (bridges += `decision_id text`), each funded under its own journal key.

- [ ] Tests: `test_capacity_bound_by_cushion_on_cautious_band` (Sam: limit 150 → 90),
  `test_outstanding_reduces_exposure`, `test_low_confidence_gives_no_auto_capacity`,
  `test_allocate_135_as_sam_90_emma_45`, `test_jordan_obligation_blocks`, `test_repayment_shortfall_blocks`.

### Task 8: Safe repayment

`repay_due`: require a synced deposit ≥ 50% of `Projection.paycheck` dated after `funded_at`, AND cautious
balance next 7 days − amount ≥ repay floor; else defer with private event "Expected repayment after your
next verified payday". Tests: `test_no_paycheck_no_repay`, `test_repay_that_causes_dip_defers`.
**PR #B (Tasks 6–8).**

### Task 9: Demo network (Emma optional) + reset

`seed/personas.py`: Emma 32 salaried; tune via engine (same linear-offset trick as Maya): Maya need 135,
Sam cautious capacity 90 (agreement limit 150), Jordan capacity 0 (mortgage in window), Emma ≥45.
`demo.DEMO_PERSONAS`, cron, app DEMO list += emma. `seed.agreements.setup_demo`. Test asserts guardian
output on seed fixtures. Manual: Auth0 user `emma@runway.demo` → `AUTH0_PERSONAS`.
**Fallback (if blocked by 03:00 EDT):** keep 3 users, single transfer Sam $90 (+ Jordan blocked).

### Task 10: Circles UI (apple-design skill)

Rename tab Family → Circles (`/family` redirects). Sections: Safety net switch, My Supporters, People I
Support (limit stepper, mode, pause), Quiet Support consent sheet with privacy summary, Activity (support
received/provided/repayments/pending/failed). Today: "Your Safety Net" card. Keep visual identity.

### Task 11: Judging prep

Browser E2E of the demo path; one verified Nessie transfer; one blocked transfer; one 403 privacy
demonstration (`curl` as Sam for Maya's `/me` → own data only / `/support` shows no balance);
`/demo/reset` reproducible; README + docs/SAFETY_NET.md update; demo script (3 min) + video script (2 min);
make repo public; Devpost text.

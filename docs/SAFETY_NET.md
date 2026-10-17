# The safety net: Circles, Quiet Support, Network Guardian

> Runway predicts a shortfall, checks who has agreed to help and how much each can give **safely**,
> moves real Nessie money, and brings it back after the next verified payday — without anyone seeing
> anyone else's balance. *Support without the spotlight.*

**Prediction → Consent → Protection → Coordination → Transfer → Repayment → Accountability**

## 1. Consent — Quiet Support Agreements (`app/agreements.py`, `db/agreements_repo.py`)

- One agreement per supporter → recipient. It is **active** only when the supporter said yes, the
  recipient said yes, nobody revoked it, and the supporter's limit isn't paused.
- The supporter sets their limit (setting it in the app is their authorization). The recipient opts in
  from their own side. Either can stop at any time; help then waits for both to agree again. Stopping never
  erases money already out — it still comes back.
- Every change bumps a **version** and writes an audit row (`support_agreement_events`). A waiting
  approval or transfer re-checks the version under lock: a change in between means nothing moves.
- **Legacy limits are not consent.** Limits set before agreements existed were migrated in with no consent
  stamps (audited `migrated_without_consent`); approval requests from before were declined. The demo
  relationships get both consents through an auditable setup step (`demo_setup`).
- A Circle is people you trust; joining one grants **nothing** financial.

## 2. Protection — Network Guardian (`app/guardian.py`, pure, no LLM)

For each consenting supporter, over the whole time the money would be out (today → recipient's payday + grace):

```
cash room     = lowest cautious (p5) balance in that window − the supporter's own cushion
pair room     = their limit for this person − what this person already owes them
exposure room = their total cap across everyone − everything they've committed (incl. waiting approvals)
capacity      = round down to $5 of max(0, min(cash, pair, exposure))
```

No automatic capacity unless the supporter's forecast is **confident**. A supporter who is borrowing right
now never lends (no chains). The recipient's need is rounded up to $5, and is refused if repaying it on
payday would cause a new predicted shortfall in the week after.

**Allocation:** fewest supporters first (largest capacity first, ties by name, so the same inputs always
give the same answer). If automatic room can't cover the whole need, one supporter whose own cushion allows
it is asked to approve (in the app, or by Auth0 push when configured).

## 3. Coordination + transfer (`app/safety_net.py`, `app/reconcile.py`, `nessie/moves.py`)

- One decision → one **bridge per supporter share**, each with its own repayment obligation.
- Under the borrower's and every supporter's **advisory lock**, each share is re-validated from fresh rows
  (agreement + version, no chains, exposure, pair limit) right before anything moves.
- Every move is written to `transfer_journal` in the same transaction as its claim, **before** Nessie is
  called, and tagged `[rw:<key>]` in both memos (user memos can't forge a tag).
- A clear rejection (4xx) means nothing moved. A timeout/5xx means **unknown**: the bridge goes to
  `reconcile` and is never retried. The reconciler settles it only when Nessie shows exactly one tagged
  transfer and one tagged deposit for the right amount; anything else waits for a person.
- Partial success is recorded and reported as partial ("covered $90 of $135"), never as "covered".

## 4. Repayment

Only when **all** hold: a real paycheck deposit has landed since the bridge was funded (Runway's own moves
excluded); the balance stays at or above the recipient's cushion; and the forecast for the next week doesn't
dip because of it. Otherwise it waits — shown as "expected after your next verified payday", never promised.
A repayment retry happens only after an attempt that certainly moved nothing.

## 5. Privacy (server-side)

A supporter sees: who, their own limit, their own transfers and status, what's owed to them, and when it's
expected back. They **never** see the recipient's balance, income, bills, purchases, categories, forecast,
the reason, or other supporters. The recipient never sees a supporter's balance or capacity. Enforced in the
API views (`safety_views.for_lender`, `support_summary`) and proven on the real routes with real tokens
(`tests/test_privacy_network.py`). Notifications carry no dates or reasons. Ask Runway refuses questions
about someone else's money before any model runs (`app/agent/privacy.py`; `evals/privacy_eval.py`).

## Demo scenario (pinned in `tests/test_demo_scenario.py`)

| Person | Role | Authorized | Why | Safe |
|---|---|---|---|---|
| Maya, 20 | short $135 before payday | — | rent before payday | — |
| Sam, 60 | supporter | $150 | $1,450 loan payment inside the window | **$90** |
| Jordan, 40 | supporter | $300 | $1,850 mortgage on the 24th, $1,500 family cushion | **$0** |
| Emma, 32 | supporter | $45 | steady salary | **$45** |

**Several people short at once (Demo 5).** Alex (22, Maya's roommate) is $85 short the same week; Sam backs
him too ($100), and Emma ($50). Sam's $90 of safe room is shared, so the Guardian splits the week's needs
together (`guardian.allocate_network`) with a written fairness rule — **fewest options first** (least spare
capacity beyond the need), then earliest shortfall, then name order: Maya (no alternative to Sam) gets Sam
$90 + Emma $45; Alex gets Emma's $50 and $35 stays uncovered — $185 of $220 covered vs $135 first-come.
Pinned in `tests/test_demo_scenario.py` for every demo day.

Reset: the demo accounts' **Reset demo** button (Circles) rebuilds all four and holds automatic help for an
hour, so the cover happens live when someone taps **Cover it with my circle**.

## Auth0 push approvals (optional)

Built (`app/auth0_ciba.py`): over-limit approvals go to the supporter's phone when `AUTH0_CIBA_CLIENT_ID`,
`AUTH0_CIBA_CLIENT_SECRET` and `AUTH0_CIBA_USERS` are set and the supporter enrolled in Auth0 Guardian.
Without them, approvals happen in the app.

## Limits (said out loud)

A prototype on the Nessie sandbox: not production banking, no regulatory compliance, no guaranteed
repayment, no credit underwriting. No partial repayment. A top-up after a partially funded decision waits
for the next pass once the open bridges settle.

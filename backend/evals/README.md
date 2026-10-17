# Evals

Both evals run in CI through `tests/test_evals.py`, so a change that makes the agent or the forecast
worse fails the build. Both score the seeded personas (Maya, Jordan, Sam) from the same generator
that seeded Nessie, so results are reproducible offline. Run them by hand from `backend/`:

```bash
python -m evals.agent_eval            # rule-based router, offline
python -m evals.agent_eval --gemini   # Gemini (needs GEMINI_API_KEY)
python -m evals.forecast_backtest
```

## Agent eval

48 questions across the three personas, ground truth from the deterministic tools: 30 "can I afford
$X on day Y?" (10 per persona, five phrasings, 15 safe and 15 not), 6 "fix it", 3 subscription,
3 forecast and 6 peer-to-peer questions. Each question is asked as its persona, so Gemini answers in
that persona's voice: Maya (20) genz, Jordan (40) direct, Sam (60) classic.

The peer-to-peer cases (`who_owes_me` and `request_money`):

- "Who owes me money?" and "Did anyone pay me back yet?": the reply quotes the total owed, summed by the tool.
- "Split dinner $60 with Alex" ($30.00) and "Ask Alex for $45 for concert tickets" ($45.00): a pending
  `p2p_request` for exactly that amount, quoted in the reply.
- "split the $100 cab with Alex and Priya": the grounding case. $33.33 is in no message, so the reply
  can only quote it from the tool's output.
- "ask Bob for $20": no such contact, so the right answer creates no pending action and asks which contact.

- **Tool selection:** the expected tool was called.
- **Answer accuracy:** the verdict, the proposed transfer amount (or no proposal when nothing needs
  fixing), or the key figure is right.
- **Grounded figures:** every `$` figure in the reply came from a tool output or the user's own
  message. This is how "the LLM never does math" is measured, not just promised.

| Agent | Questions | Tool selection | Answer accuracy | Grounded figures | API errors |
|---|---|---|---|---|---|
| Gemini — Maya (genz voice) | 16 | 100% | 100% | 100% | 0 |
| Gemini — Jordan (direct voice) | 13 | 100% | 92% | 100% | 0 |
| Gemini — Sam (classic voice) | 13 | 100% | 92% | 100% | 0 |
| **Gemini (`gemini-3.8-flash`, free tier) — all** | 42 | **100%** | **95%** | **100%** | 0 |
| Rule-based router (offline baseline) | 48 | 100% | 100% | 100% | — |

The Gemini rows are from the 42 questions before the peer-to-peer cases were added; they haven't
been rerun on those 6 yet. Gemini run on 2026-10-17 after the round-2 changes (readiness, range and confidence in every tool
result), with runtime grounding enforced. Both misses were "can I afford it?" questions whose right
answer was no. Sam's reply was a correct no worded "I would advise against purchasing…", which the
grader didn't know; "advise against" is now a grader test. Jordan's question passed when rerun, so
that miss was a phrasing the grader couldn't read, not a wrong verdict. The table keeps the original
run's score. An earlier run's miss ("That purchase would put your account into an overdraft…") stays a
grader limit: adding "overdraft" would misread a correct "yes, without an overdraft".

Notes on method:

- **API errors** count as failures, so a silent fallback to the router can never pass as a Gemini answer.
  Free-tier runs sometimes hit transient 403s, which is why the agent retries each request once.
- **Answer accuracy** reads the verdict from the reply's first sentence with a keyword list ("not",
  "can't", "hold off", …). Keyword grading can miss new phrasings; every miss so far was a correct
  answer worded differently, and each one became a grader test in `tests/test_evals.py`.
- **Grounded figures** checks the reply against every tool output the agent actually received, so a
  reply may cite another tool it chose to call, but never a number no tool produced.
- Runs vary: single questions occasionally fail on wording or an API error. The table shows one run.

## Forecast backtest

Fit on months 1–3 of each persona's seeded history, predict month 4. A fold builds the schedule from
the first 90 days only — bills, paydays and fixed transfers detected from history, and the spend
model — then predicts the checking balance for each of the next 30 days. 18 folds: 3 personas × 6
seed days (each seed day generates a different history).

| Spend model | MAE, daily checking balance | MAPE, month-4 everyday spend |
|---|---|---|
| Weekday means, 90 days | $134.47 | 23.3% |
| Flat daily mean, 90 days (live) | $137.65 | 24.1% |
| Last 30 days repeated (naive) | $163.09 | 33.9% |
| No everyday spending (bills only) | $407.91 | 100.0% |

**Reading it honestly:**

- Learning everyday spend from 90 days cuts the balance error by 66% against ignoring it, and by 16%
  against repeating last month.
- Everyday spending is booked on the day it's expected. An earlier version booked each week's
  estimate on the week's first day, which took unspent money out of "today" and moved the low point;
  fixing that cut the live model's error from $160 to $138. The spending rate is learned from the
  days the history actually covers (up to 90), so a new user's rate isn't divided by days with no data.
- Weekday means and the flat mean tie (within 1%): the seed generator draws purchases independently
  of the weekday, so there is no weekday pattern to find. The live forecast uses the simpler flat mean;
  real transaction data would be the test of whether the weekday model earns its place.
- Single folds vary a lot because a month of random purchases varies a lot: Jordan's worst fold had
  half his usual purchases in month 4, so every average-based model over-predicted by ~97%.

## Learning curve and forecast range

How does it learn? The same backtest, but the live model may only learn from the last N days before
the cutoff, as if Runway had just met the person. Same 18 folds.

| Days of history | MAE, daily balance | p5–p90 band coverage | Days below the low end | Payday found |
|---|---|---|---|---|
| 14 | $2,700.01 | 13% | 4% | 0% |
| 30 | $2,737.30 | 19% | 0% | 0% |
| 60 | $198.69 | 88% | 0% | 100% |
| 90 | $137.65 | 91% | 1% | 100% |

- **Coverage** is the share of month-4 days whose actual balance landed inside the forecast's band.
  The band is asymmetric, p5–p90 of the balance, so a calibrated one holds about 85%. On these
  seeded personas it now holds 91%: wider than needed, on purpose (see the calibration note below).
- **Days below the low end** is the number the safety net cares about, because it plans on
  `balance_low`. With a symmetric p10–p90 band, 13% of real days fell below the low end, and in 4 of
  18 months the real lowest day was under the forecast's cautious low. Setting the low end from p95
  spending brought that to 8% of days and 3 of 18 months. Going to p97 only saved one more month
  while widening the band for everyone, so the leftover misses come from what the band doesn't model
  (paycheck amounts, irregular P2P), not from the quantile.
- **The cliff between 30 and 60 days is the payday.** The detector needs three paychecks on a steady
  rhythm before it puts income in the forecast (biweekly: ~5 weeks; monthly: ~2 months). Without
  income, the forecast misses every paycheck in month 4, which is where a $2,700 error comes from.
  That is exactly what readiness reports: with no payday found, the status is "calibrating" or
  "learning", never "confident", and the safety net won't act on it automatically.
- Coverage at 14–30 days is low for the same reason: the band models everyday spending, not a
  missing paycheck.

**How the band is built (`app/forecast/band.py`):** a moving-block bootstrap over the daily spending
totals the rate was learned from: 400 simulated months, each stitched from real 7-day stretches of the
person's history; the band at day k runs from the p95 to the p10 of total spending by day k (a p5–p90
balance). Two choices matter:

- **Quantiles of the running total, not per-day quantiles summed.** Big and small days average out
  over a month, so the sum of 30 daily p90s is far more than the p90 of a month: the band would be
  much too wide by month-end.
- **Weekly blocks, not single days.** Spending clusters (a weekly grocery run, a busy weekend);
  resampling whole weeks keeps those clusters, so the band isn't falsely narrow.

Only everyday spending is treated as uncertain; bills and paydays are taken as scheduled.

**Calibrated on outside data (`ml/`).** The seed generator draws purchases independently each day,
which is the one setting where a plain bootstrap is right. On outside data it wasn't: its cautious end
was beaten 12–43% of the time instead of 5% (IBM card users, a real UK account, real Czech accounts),
because it misses month-to-month swings in spending. The live band widens the bootstrap by factors
learned with split conformal calibration (×3.3 at 30 days of history, ×2.0 at 60, ×1.6 at 90), which
brings that to 5–11% on data it never saw (Berka at 30 days is the exception). The cost is the table above: on our own personas the band is
now wider than they need. We calibrate to the outside data, not to our own generator. Full results in
`ml/README.md`.


## Tone eval

*How* the agent talks, not just *what* it says. Real Gemini replies in each voice, to the same three
questions, once with money tight (Maya's seeded data, overdraft risk) and once with money fine (Sam's,
healthy). Every check is a plain rule on the text (`evals/tone_eval.py`), so nothing is judged by
another model:

- **Gen Z voice** (users under 30), one steady voice: no cringe phrases ("bestie", "slay", "no cap"…),
  at most one Gen Z touch per reply, no bank-letter phrasing ("you are projected to", "leaving you"…),
  sounds casual (uses contractions), no emoji when money is tight and at most one when it's fine.
- **Direct and classic voices** (30–49, 50+): no Gen Z words, no emoji.

| Voice | Money | Before (old prompt) | After |
|---|---|---|---|
| Gen Z | tight | 1/3 — read like a bank letter | **3/3** |
| Gen Z | fine | 2/3 — piled on slang | **3/3** |
| Direct | tight / fine | 3/3 · 3/3 | 3/3 · 3/3 |
| Classic | tight / fine | 3/3 · 3/3 | 3/3 · 3/3 |

The old Gen Z prompt said "not Gen Z, no slang" when money was tight and "playful Gen Z, a celebration"
when it was fine, so the voice flipped between a bank letter and a group chat. The new one keeps one
voice and only changes the mood. Runs on 2026-10-17, `gemini-3.8-flash`; three replies per cell is a
small sample, so treat this as a regression check rather than a precise rate. The rules are unit-tested
in `tests/test_evals.py`. Run it with `python -m evals.tone_eval` (needs `GEMINI_API_KEY`).

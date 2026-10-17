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

42 questions across the three personas, ground truth from the deterministic tools: 30 "can I afford
$X on day Y?" (10 per persona, five phrasings, 15 safe and 15 not), 6 "fix it", 3 subscription and
3 forecast questions. Each question is asked as its persona, so Gemini answers in that persona's
voice: Maya (20) genz, Jordan (40) direct, Sam (60) classic.

- **Tool selection:** the expected tool was called.
- **Answer accuracy:** the verdict, the proposed transfer amount (or no proposal when nothing needs
  fixing), or the key figure is right.
- **Grounded figures:** every `$` figure in the reply came from a tool output or the user's own
  message. This is how "the LLM never does math" is measured, not just promised.

| Agent | Questions | Tool selection | Answer accuracy | Grounded figures | API errors |
|---|---|---|---|---|---|
| Rule-based router (offline baseline) | 42 | 100% | 100% | 100% | — |

Gemini results on the three-persona set are added once the current run completes. On the earlier
Maya-only set (40 questions) Gemini scored 100% / 100% / 100% with 0 API errors.

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
| Weekday means, 90 days | $158.65 | 22.7% |
| Flat daily mean, 90 days (live) | $160.07 | 23.5% |
| Last 30 days repeated (naive) | $197.30 | 33.9% |
| No everyday spending (bills only) | $407.91 | 100.0% |

**Reading it honestly:**

- Learning everyday spend from 90 days cuts the balance error by 61% against ignoring it, and by 19%
  against repeating last month.
- Weekday means and the flat mean tie (within 1%): the seed generator draws purchases independently
  of the weekday, so there is no weekday pattern to find. The live forecast uses the simpler flat mean;
  real transaction data would be the test of whether the weekday model earns its place.
- Single folds vary a lot because a month of random purchases varies a lot: Jordan's worst fold had
  half his usual purchases in month 4, so every average-based model over-predicted by ~97%.

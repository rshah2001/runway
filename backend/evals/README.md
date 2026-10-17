# Evals

Both evals run in CI through `tests/test_evals.py`, so a change that makes the agent or the forecast
worse fails the build. Run them by hand from `backend/`:

```bash
python -m evals.agent_eval            # rule-based router, offline
python -m evals.agent_eval --gemini   # Gemini (needs GEMINI_API_KEY)
python -m evals.forecast_backtest
```

## Agent eval

40 questions, ground truth from the deterministic tools: 30 "can I afford $X on day Y?" in five
phrasings (19 not safe, 11 safe), 4 "fix it", 3 subscription and 3 forecast questions.

- **Tool selection:** the expected tool was called.
- **Answer accuracy:** the verdict, the proposed transfer amount or the key figure is right.
- **Grounded figures:** every `$` figure in the reply came from a tool output or the user's own
  message. This is how "the LLM never does math" is measured, not just promised.

| Agent | Questions | Tool selection | Answer accuracy | Grounded figures | API errors |
|---|---|---|---|---|---|
| Gemini (`gemini-3.8-flash`, free tier, with personality) | 40 | 100% | 100% | 100% | 0 |
| Rule-based router (offline baseline) | 40 | 100% | 100% | 100% | — |

Gemini run on 2026-10-17 with the personality prompt and the status-driven tone dial. Notes on method:

- **API errors** count as failures, so a silent fallback to the router can never pass as a Gemini answer.
  Free-tier runs sometimes hit transient 403s, which is why the agent retries each request once.
- **Answer accuracy** reads the verdict from the reply's first sentence with a keyword list ("not",
  "can't", "hold off", …). Keyword grading can miss new phrasings; every miss so far was a correct
  answer worded differently, and each one became a grader test in `tests/test_evals.py`.
- **Grounded figures** checks the reply against every tool output the agent actually received, so a
  reply may cite another tool it chose to call, but never a number no tool produced.
- Runs vary: across five runs on the same day, single questions occasionally failed on wording or an API
  error. The table shows the latest run.

## Forecast backtest

Bills, subscriptions and paychecks are scheduled, so they forecast exactly. Everyday card spending is
the uncertain part, so that is what's scored. Each fold fits on 90 days of history and predicts the
next 30; 30 folds (5 history seeds × 6 cutoffs).

| Method | MAE, cumulative spend ($/day) | MAPE, 30-day total |
|---|---|---|
| Learned: weekday means | $69.63 | 16.1% |
| Learned: flat daily mean | $69.86 | 16.1% |
| Schedule dials (live today) | $140.03 | 37.6% |

**Reading it honestly:** learning from history halves the error of the hand-set dials, which
under-predict spending by ~40%. The weekday model ties the flat mean because the seeded history has
no weekday pattern; real transaction data would be the test of whether it earns its place.

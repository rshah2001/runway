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

| Agent | Questions | Tool selection | Answer accuracy | Grounded figures |
|---|---|---|---|---|
| Rule-based router (offline baseline) | 40 | 100% | 100% | 100% |
| Gemini | 40 | _not run yet_ | | |

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

"""Run both evals in CI: a change that makes the agent or the forecast worse fails the build."""

import pytest

from app.agent import chat as agent
from evals import agent_eval, forecast_backtest


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)  # CI scores the deterministic router


def test_router_baseline_is_perfect_on_every_metric() -> None:
    rows = agent_eval.run()
    failures = [r for r in rows if not (r["tool"] and r["answer"] and r["grounded"])]
    assert len(rows) == 51 and failures == []


def test_eval_has_both_verdicts() -> None:
    verdicts = [c.truth.get("verdict") for c in agent_eval.build_cases()]
    assert verdicts.count("safe") >= 8 and verdicts.count("not_safe") >= 8


def test_grounding_check_catches_an_invented_figure() -> None:
    truth = {"lowest_balance": "$251.61"}
    assert agent.grounded("Lowest is $251.61.", "how low?", truth)
    assert not agent.grounded("You'll have about $900.", "how low?", truth)
    assert agent.grounded("Yes, the $180 concert is fine.", "can I spend $180?", truth)


def test_live_spend_model_beats_the_naive_baselines() -> None:
    results = forecast_backtest.run()
    live = results["Flat daily mean, 90 days (live)"]
    assert live.mae < results["Last 30 days repeated (naive)"].mae
    assert live.mae < results["No everyday spending (bills only)"].mae


@pytest.mark.parametrize(
    ("reply", "says_safe"),
    [
        ("Spending $35.00 on Wed Oct 21 isn't safe, as your balance would drop.", False),
        ("Buying it is not safe because you'd fall to $71.61.", False),
        ("Yes, you can afford it — the lowest you'd hit is $517.89 on Tue Dec 1.", True),
        ("Not safely — you'd drop to $71.61 on Thu Nov 5.", False),
        ("You can buy it on Fri Nov 6, but your balance already dips below your floor on Thu Nov 5.", True),
        ("I would hold off on the $120.00 concert for tomorrow.", False),
        ("I would advise against purchasing the $6,500.00 concert ticket tomorrow, as it would drop.", False),
    ],
)
def test_verdict_grader_reads_the_first_sentence(reply: str, says_safe: bool) -> None:
    first = agent_eval.SENTENCE_END.split(reply, maxsplit=1)[0].lower()
    assert (agent_eval.NEGATIVE.search(first) is None) == says_safe


def test_learning_curve_gets_better_with_history_and_the_band_is_honest() -> None:
    curve = forecast_backtest.learning_curve()
    assert curve[90].mae < curve[60].mae < curve[30].mae  # it learns: more history, smaller error
    assert curve[60].payday_found == curve[90].payday_found == 1.0
    assert 0.70 <= curve[90].coverage <= 0.95  # a p5–p90 band should hold ~85% of real days
    assert curve[90].below_low <= 0.10  # the safety net plans on the low end: it must rarely be beaten
    assert curve[90].coverage > curve[30].coverage

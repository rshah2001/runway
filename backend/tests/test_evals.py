"""Run both evals in CI: a change that makes the agent or the forecast worse fails the build."""

import pytest

from evals import agent_eval, forecast_backtest


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)  # CI scores the deterministic router


def test_router_baseline_is_perfect_on_every_metric() -> None:
    rows = agent_eval.run()
    failures = [r for r in rows if not (r["tool"] and r["answer"] and r["grounded"])]
    assert len(rows) == 40 and failures == []


def test_eval_has_both_verdicts() -> None:
    verdicts = [c.truth.get("verdict") for c in agent_eval.build_cases()]
    assert verdicts.count("safe") >= 8 and verdicts.count("not_safe") >= 8


def test_grounding_check_catches_an_invented_figure() -> None:
    truth = {"lowest_balance": "$251.61"}
    assert agent_eval._grounded("Lowest is $251.61.", "how low?", truth)
    assert not agent_eval._grounded("You'll have about $900.", "how low?", truth)
    assert agent_eval._grounded("Yes, the $180 concert is fine.", "can I spend $180?", truth)


def test_learned_spend_model_beats_the_hand_set_dials() -> None:
    results = forecast_backtest.run()
    dials = results["Schedule dials (live today)"]
    assert results["Learned: flat daily mean"].mae < dials.mae
    assert results["Learned: weekday means"].mae < dials.mae

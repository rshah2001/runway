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
    assert len(rows) == 58 and failures == []


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
    assert curve[30].payday_found == 1.0 and curve[30].mae < 400  # two paychecks are enough: no 30-day cliff


# ---------- tone eval rules (the Gemini run is manual; the rules themselves are tested here) ----------
from evals import tone_eval  # noqa: E402


def _passes(voice: str, state: str, reply: str) -> dict[str, bool]:
    return {name: rule(reply) for name, rule in tone_eval.checks_for(voice, state).items()}


def test_tone_rules_pass_a_good_genz_reply_in_both_moods() -> None:
    tight = "You're gonna dip below your floor on Thu Nov 5. I can move some from savings, want me to?"
    fine = "You're good all month, tbh. Nice."
    assert all(_passes("genz", "tight", tight).values()) and all(_passes("genz", "fine", fine).values())


def test_tone_rules_catch_a_bank_letter_and_overdoing_it() -> None:
    letter = "You will dip below your floor, leaving you short. I am confident in this forecast."
    assert not _passes("genz", "tight", letter)["not a bank letter"] and not _passes("genz", "tight", letter)["casual"]
    assert not _passes("genz", "fine", "You're fine, lowkey thriving, ngl.")["light touch"]
    assert not _passes("genz", "fine", "You're doing great, bestie.")["no cringe"]
    assert not _passes("genz", "tight", "You're gonna dip on Nov 5 😬")["emoji"]  # no emoji when money's tight


def test_tone_rules_keep_slang_out_of_adult_voices() -> None:
    assert all(_passes("direct", "tight", "Heads up: you'll come up short when rent clears.").values())
    assert not _passes("classic", "fine", "You're in good shape, tbh.")["no Gen Z words"]


def test_privacy_eval_passes_on_the_deterministic_path(monkeypatch) -> None:
    """Nobody can get another person's money out of Ask Runway — and own-relationship questions still work."""
    from evals import privacy_eval

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert privacy_eval.run(use_gemini=False) == 0


def test_guardian_keeps_every_promise_on_generated_networks() -> None:
    """Pair limit, exposure, cushion, no overshoot, confidence, determinism — zero violations."""
    from evals import guardian_eval

    assert guardian_eval.run(scenarios=300) == 0


def test_privacy_eval_with_gemini_does_not_count_the_fallback_as_a_pass(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A dead key used to score 15/15 because chat() quietly fell back to the router."""
    from evals import privacy_eval

    class DeadGemini:
        class interactions:  # noqa: N801 — mimics the SDK's client.interactions
            @staticmethod
            def create(**_: object) -> None:
                raise RuntimeError("402: prepayment credits are depleted")

    monkeypatch.setenv("GEMINI_API_KEY", "dead-key-for-the-test")
    monkeypatch.setattr(agent, "_gemini_client", DeadGemini)
    monkeypatch.setattr(agent, "_chat_with_gemini", agent._chat_with_gemini)  # restored after the test
    monkeypatch.setattr(agent, "RETRY_DELAY_S", 0)
    assert privacy_eval.run(use_gemini=True) == 1
    out = capsys.readouterr().out
    assert "where Gemini didn't answer" in out and "15/15" not in out

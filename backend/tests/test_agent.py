"""Agent tests: the tools' numbers, the rule-based router, and Gemini's tool loop with a fake client."""

from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest

from app.agent import chat as agent
from app.agent import tools

TODAY = date(2026, 10, 16)  # Friday; Maya's low is $251.61 on Thu Nov 5, floor $300


# ---------- tools ----------


@pytest.mark.parametrize(
    ("when", "expected"),
    [
        (None, date(2026, 10, 17)),
        ("today", TODAY),
        ("friday", date(2026, 10, 23)),  # said on a Friday: next week's
        ("next Monday", date(2026, 10, 19)),
        ("2026-12-01", date(2026, 12, 1)),
    ],
)
def test_resolve_date(when: str | None, expected: date) -> None:
    assert tools.resolve_date(when, TODAY) == expected


def test_resolve_date_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        tools.resolve_date("the 5th", TODAY)


def test_concert_is_not_safe_until_after_payday() -> None:
    r = tools.simulate_purchase(180, "friday", "Concert", today=TODAY)
    assert r["verdict"] == "not_safe"
    assert (r["lowest_balance_with_it"], r["lowest_day_with_it"]) == ("$71.61", "Thu Nov 5")
    assert r["shortfall"] == "$228.39"
    assert r["first_safe_day"] == "Fri Nov 6"
    assert r["transfer_that_would_cover_it"] == "$250.00"


def test_purchase_after_the_dip_is_safe_but_flags_the_dip() -> None:
    r = tools.simulate_purchase(40, "2026-11-07", today=TODAY)
    assert r["verdict"] == "safe"
    assert r["already_below_floor_without_it"] is True


@pytest.mark.parametrize("amount", [0, -0.0, 1e9])
def test_simulate_rejects_silly_amounts(amount: float) -> None:
    with pytest.raises(ValueError):
        tools.simulate_purchase(amount, today=TODAY)


def test_recurring_totals_are_computed_not_left_to_the_model() -> None:
    r = tools.find_recurring(today=TODAY)
    assert r["count"] == 3
    assert r["monthly_total"] == "$37.47" and r["yearly_total"] == "$449.64"


def test_propose_transfer_sizes_the_fix_and_moves_nothing() -> None:
    r = tools.propose_transfer(today=TODAY)
    assert r["transfer"] == "$50.00" and r["lowest_balance_after"] == "$301.61"
    action = tools.PENDING[r["action_id"]]
    assert action.status == "awaiting_approval" and action.amount == 50


def test_propose_transfer_can_cover_a_purchase() -> None:
    assert tools.propose_transfer(180, "friday", today=TODAY)["transfer"] == "$250.00"


def test_propose_transfer_refuses_more_than_savings_holds() -> None:
    r = tools.propose_transfer(5000, "today", today=TODAY)
    assert r["possible"] is False and "action_id" not in r


def test_tool_errors_come_back_as_data() -> None:
    assert "error" in tools.call("simulate_purchase", {"amount": 10, "when": "someday"}, TODAY)
    assert "error" in tools.call("simulate_purchase", {"bogus": 1}, TODAY)
    assert "error" in tools.call("delete_account", {}, TODAY)


# ---------- rule-based router (no API key) ----------


def test_demo_question_is_answered_without_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    r = agent.chat("Can I go to the concert Friday? $180", today=TODAY)
    assert r.tool_calls == ["simulate_purchase"]
    assert "Not safely" in r.reply and "$71.61" in r.reply


@pytest.mark.parametrize("text", ["on the 5th, $40?", "2 tickets for $40", "can I spend 40 dollars?"])
def test_amount_parsing_ignores_other_numbers(text: str) -> None:
    assert agent._amount_in(text) == 40


def test_overlong_message_is_refused_before_any_tool_runs() -> None:
    r = agent.chat("a" * (agent.MAX_MESSAGE_CHARS + 1), today=TODAY)
    assert r.tool_calls == [] and r.pending_action is None


def test_unreadable_date_is_a_reply_not_a_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert "too far ahead" in agent.chat("can I afford $50 on 2028-01-01?", today=TODAY).reply


# ---------- Gemini loop with a scripted fake client ----------


class FakeGemini:
    """Plays back scripted interactions and records what the agent sent."""

    def __init__(self, *turns: SimpleNamespace) -> None:
        self.turns = list(turns)
        self.sent: list[dict[str, Any]] = []
        self.interactions = self

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.sent.append(kwargs)
        return self.turns.pop(0)


def _calls(*calls: tuple[str, dict[str, Any]]) -> SimpleNamespace:
    steps = [
        SimpleNamespace(type="function_call", name=n, arguments=a, id=f"call-{i}") for i, (n, a) in enumerate(calls)
    ]
    return SimpleNamespace(id="int-1", steps=steps, output_text=None)


def _text(text: str) -> SimpleNamespace:
    return SimpleNamespace(id="int-2", steps=[], output_text=text)


def test_gemini_tool_result_is_fed_back_and_reply_returned() -> None:
    fake = FakeGemini(_calls(("simulate_purchase", {"amount": 180, "when": "friday"})), _text("Not safely."))
    r = agent.chat("Can I go to the concert Friday? $180", client=fake, today=TODAY)
    assert (r.reply, r.tool_calls) == ("Not safely.", ["simulate_purchase"])
    second = fake.sent[1]
    assert second["previous_interaction_id"] == "int-1"
    assert second["input"][0]["call_id"] == "call-0" and "$71.61" in second["input"][0]["result"][0]["text"]


def test_gemini_proposal_surfaces_as_a_pending_action() -> None:
    fake = FakeGemini(_calls(("propose_transfer", {})), _text("I can move $50 — approve?"))
    r = agent.chat("fix it", client=fake, today=TODAY)
    assert r.pending_action is not None and r.pending_action.amount == 50


def test_only_one_transfer_can_be_proposed_per_message() -> None:
    fake = FakeGemini(_calls(("propose_transfer", {}), ("propose_transfer", {})), _text("Approve?"))
    r = agent.chat("fix it twice", client=fake, today=TODAY)
    results = fake.sent[1]["input"]
    assert "action_id" in results[0]["result"][0]["text"]
    assert results[1]["is_error"] is True
    assert r.pending_action is not None


def test_numbers_without_a_tool_call_are_discarded() -> None:
    fake = FakeGemini(_text("Sure, you'll have about $900 left."))  # invented figure
    r = agent.chat("can I afford $180 friday", client=fake, today=TODAY)
    assert "$900" not in r.reply and r.tool_calls == ["simulate_purchase"]  # answered by the router


def test_gemini_failure_falls_back_to_rules() -> None:
    class Broken:
        class interactions:  # noqa: N801 — mirrors the SDK's attribute name
            @staticmethod
            def create(**_: Any) -> None:
                raise ConnectionError("quota exceeded")

    r = agent.chat("fix it", client=Broken(), today=TODAY)
    assert r.pending_action is not None and r.tool_calls == ["propose_transfer"]


# ---------- personality: the tone dial is computed, not judged by the model ----------


@pytest.mark.parametrize(
    ("low", "expected"),
    [(299.99, "overdraft_risk"), (300, "tight"), (449.99, "tight"), (450, "healthy"), (-50, "overdraft_risk")],
)
def test_status_thresholds(low: float, expected: str) -> None:
    from app.forecast import engine

    assert engine.status(low, 300) == expected


def test_tools_hand_the_model_its_tone_inputs() -> None:
    f = tools.get_forecast(today=TODAY)
    assert f["status"] == "overdraft_risk" and f["low_point_under_100"] is False
    concert = tools.simulate_purchase(180, "friday", today=TODAY)
    assert concert["status"] == "overdraft_risk" and concert["low_point_under_100"] is True  # $71.61
    later = tools.simulate_purchase(40, "2026-11-07", today=TODAY)
    assert later["verdict"] == "safe" and later["status"] == "overdraft_risk"  # Nov 5 dip still coming
    assert tools.find_recurring(today=TODAY)["status"] == "overdraft_risk"


def test_system_prompt_carries_the_current_status() -> None:
    fake = FakeGemini(_text("You're short on Nov 5."))
    agent.chat("how am I doing?", client=fake, today=TODAY)
    assert "Current status: overdraft_risk." in fake.sent[0]["system_instruction"]

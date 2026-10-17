"""Agent tests: the tools' numbers, the rule-based router, and Gemini's tool loop with a fake client.

Expected figures are computed from the engine rather than hard-coded: these tests check that the
tools report the engine's numbers faithfully, and the engine's own math is tested in test_forecast.
"""

import re
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest

from app.agent import chat as agent
from app.agent import tools, voice
from app.forecast import engine, sources

TODAY = date(2026, 10, 16)  # a Friday; Maya is short before payday, Sam is comfortable


def _money(text: str) -> float:
    return float(text.replace("$", "").replace(",", ""))


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


def test_forecast_tool_reports_the_engines_low_point() -> None:
    f = engine.forecast(start=TODAY, persona="maya")
    r = tools.get_forecast(persona="maya", today=TODAY)
    assert r["lowest_balance"] == tools.money(f.low.balance) and r["lowest_day"] == tools.day(f.low.date)
    assert r["status"] == "overdraft_risk" and r["below_safety_floor"] is True


def test_forecast_tool_says_the_real_balance_and_lists_only_scheduled_flows() -> None:
    r = tools.get_forecast(persona="maya", today=TODAY)
    assert r["balance_today"] == tools.money(engine.schedule_for("maya", TODAY).start_balance)
    assert r["upcoming"] and all("Everyday spending" not in u["label"] for u in r["upcoming"])


def test_unsafe_purchase_says_when_it_becomes_safe_and_what_would_cover_it() -> None:
    r = tools.simulate_purchase(180, "friday", "Concert", persona="maya", today=TODAY)
    assert r["verdict"] == "not_safe" and r["first_safe_day"]
    shortfall = _money(r["shortfall"])
    assert shortfall == pytest.approx(300 - _money(r["lowest_balance_with_it"]))
    assert _money(r["transfer_that_would_cover_it"]) >= shortfall  # rounded up to a tidy step


def test_safe_purchase_for_a_comfortable_persona() -> None:
    r = tools.simulate_purchase(200, "friday", persona="sam", today=TODAY)
    assert r["verdict"] == "safe" and r["status"] == "healthy" and "first_safe_day" not in r


@pytest.mark.parametrize("amount", [0, -0.0, 1e9])
def test_simulate_rejects_silly_amounts(amount: float) -> None:
    with pytest.raises(ValueError):
        tools.simulate_purchase(amount, today=TODAY)


def test_recurring_totals_are_computed_not_left_to_the_model() -> None:
    r = tools.find_recurring(persona="jordan", today=TODAY)
    monthly = sum(_money(s["amount"]) * 30 / s["every_days"] for s in r["subscriptions"])
    assert r["count"] == 8
    assert r["monthly_total"] == tools.money(monthly) and r["yearly_total"] == tools.money(monthly * 12)


def test_propose_transfer_sizes_the_fix_and_moves_nothing() -> None:
    f = engine.forecast(start=TODAY, persona="maya")
    r = tools.propose_transfer(persona="maya", today=TODAY)
    amount = _money(r["transfer"])
    assert amount % 50 == 0 and f.low.balance + amount >= 300 > f.low.balance + amount - 50  # just enough
    action = tools.PENDING[r["action_id"]]
    assert action.status == "awaiting_approval" and action.amount == amount
    assert agent.persona_of(r["action_id"]) == "maya"


def test_no_transfer_when_nothing_needs_fixing() -> None:
    r = tools.propose_transfer(persona="sam", today=TODAY)
    assert r["needed"] is False and "action_id" not in r


def test_propose_transfer_refuses_more_than_savings_holds() -> None:
    r = tools.propose_transfer(5000, "today", persona="maya", today=TODAY)
    assert r["possible"] is False and "action_id" not in r


def test_tool_errors_come_back_as_data() -> None:
    assert "error" in tools.call("simulate_purchase", {"amount": 10, "when": "someday"}, TODAY)
    assert "error" in tools.call("simulate_purchase", {"bogus": 1}, TODAY)
    assert "error" in tools.call("delete_account", {}, TODAY)
    assert "error" in tools.call("get_forecast", {}, TODAY, persona="mallory")


def test_the_model_cannot_choose_whose_data_a_tool_sees() -> None:
    as_sam = tools.call("get_forecast", {"persona": "maya"}, TODAY, persona="sam")  # injected persona is dropped
    assert as_sam == tools.get_forecast(persona="sam", today=TODAY)


# ---------- rule-based router (no API key) ----------


def test_demo_question_is_answered_without_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    r = agent.chat("Can I go to the concert Friday? $180", today=TODAY)
    truth = tools.simulate_purchase(180, "friday", today=TODAY)
    assert r.tool_calls == ["simulate_purchase"]
    assert "Not safely" in r.reply and truth["lowest_balance_with_it"] in r.reply


def test_router_answers_for_the_right_persona(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    r = agent.chat("what subscriptions do I have?", persona="jordan", today=TODAY)
    assert tools.find_recurring(persona="jordan", today=TODAY)["monthly_total"] in r.reply


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
    truth = tools.simulate_purchase(180, "friday", today=TODAY)
    assert second["previous_interaction_id"] == "int-1"
    assert second["input"][0]["call_id"] == "call-0"
    assert truth["lowest_balance_with_it"] in second["input"][0]["result"][0]["text"]


def test_gemini_proposal_surfaces_as_a_pending_action_for_the_asking_persona() -> None:
    fake = FakeGemini(_calls(("propose_transfer", {})), _text("I can move it — approve?"))
    r = agent.chat("fix it", persona="maya", client=fake, today=TODAY)
    assert r.pending_action is not None and r.pending_action.amount and r.pending_action.amount > 0
    assert agent.persona_of(r.pending_action.id) == "maya"


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


def test_an_invented_figure_after_a_tool_call_is_discarded() -> None:
    fake = FakeGemini(_calls(("get_forecast", {})), _text("You're fine, you'll have $5,000 to spare."))
    r = agent.chat("how am I doing?", client=fake, today=TODAY)
    assert "$5,000" not in r.reply and r.tool_calls == ["get_forecast"]  # the router's grounded answer


def test_figures_from_tools_or_the_user_are_allowed() -> None:
    outputs = [{"lowest_balance": "$121.71"}]
    assert agent.grounded("Your low is $121.71.", "how low?", outputs)
    assert agent.grounded("The $180 concert would hurt.", "can I spend $180?", outputs)
    assert agent.grounded("Move $50 now.", "", [{"transfer": "$50.00"}])  # same figure, no cents
    assert not agent.grounded("You'll have $900.", "how low?", outputs)


def test_gemini_failure_falls_back_to_rules() -> None:
    class Broken:
        class interactions:  # noqa: N801 — mirrors the SDK's attribute name
            @staticmethod
            def create(**_: Any) -> None:
                raise ConnectionError("quota exceeded")

    r = agent.chat("fix it", client=Broken(), today=TODAY)
    assert r.pending_action is not None and r.tool_calls == ["propose_transfer"]


# ---------- personality: the tone dial is computed, not judged by the model ----------


def test_tools_hand_the_model_its_tone_inputs() -> None:
    assert tools.get_forecast(persona="maya", today=TODAY)["status"] == "overdraft_risk"
    assert tools.get_forecast(persona="sam", today=TODAY)["status"] == "healthy"
    big = tools.simulate_purchase(500, "friday", persona="maya", today=TODAY)
    assert big["status"] == "overdraft_risk"
    later = tools.simulate_purchase(25, "2026-12-05", persona="maya", today=TODAY)
    assert later["verdict"] == "safe" and later["status"] == "overdraft_risk"  # the earlier dip still counts
    assert tools.find_recurring(persona="maya", today=TODAY)["status"] == "overdraft_risk"


def test_system_prompt_carries_the_current_status() -> None:
    for persona, status in [("maya", "overdraft_risk"), ("sam", "healthy")]:
        fake = FakeGemini(_text("Here's where you stand."))
        agent.chat("how am I doing?", persona=persona, client=fake, today=TODAY)
        assert f"Current status: {status}." in fake.sent[0]["system_instruction"]


# ---------- voices: chosen from age in code; tone only ----------


@pytest.mark.parametrize(
    ("persona", "expected"), [("maya", "genz"), ("jordan", "direct"), ("sam", "classic"), ("unknown", "genz")]
)
def test_voice_follows_persona_age(persona: str, expected: str) -> None:
    assert voice.voice_for_persona(persona) == expected


@pytest.mark.parametrize(
    ("age", "expected"), [(18, "genz"), (29, "genz"), (30, "direct"), (49, "direct"), (50, "classic")]
)
def test_voice_age_brackets(age: int, expected: str) -> None:
    assert voice.voice_for(age) == expected


def test_each_persona_gets_its_voice_and_the_same_rules() -> None:
    prompts = {}
    for persona in ("maya", "jordan", "sam"):
        fake = FakeGemini(_text("Here's where you stand."))
        agent.chat("how am I doing?", persona=persona, client=fake, today=TODAY)
        prompts[persona] = fake.sent[0]["system_instruction"]
        assert voice.VOICES[voice.voice_for_persona(persona)] in prompts[persona]
    shared = agent.SYSTEM_PROMPT.split("{voice}")
    for prompt in prompts.values():
        assert all(part.split("{")[0] in prompt for part in shared)  # accuracy rules and guardrails identical


def test_voice_examples_contain_no_figures() -> None:
    # "$" or a standalone number
    assert not any(re.search(r"\$|(?<!\w)\d", text) for text in voice.VOICES.values())


# ---------- how sure it is ----------


def _new_user(monkeypatch: pytest.MonkeyPatch, days: int) -> None:
    """Every load sees only the last `days` of history, as if Runway had just met the persona."""
    real_load = sources.load
    monkeypatch.setattr(sources, "load", lambda p, t=None, **kw: sources.recent(real_load(p, t, **kw), t, days))


def test_tools_say_how_sure_the_forecast_is() -> None:
    r = tools.get_forecast(persona="maya", today=TODAY)
    assert r["readiness"] == "confident" and r["confidence_note"].startswith("I've watched 4 months")
    assert r["track_record"].startswith("week-ahead forecasts off by $")
    assert " to " in r["lowest_balance_range"]


def test_router_keeps_confident_answers_short() -> None:
    r = agent.chat("can I afford $15 on 2026-11-07?", persona="maya", today=TODAY)
    assert "rough guide" not in r.reply and "sketch" not in r.reply


@pytest.mark.parametrize(("days", "phrase"), [(20, "day 18 of 30, so take this as a rough guide"), (10, "a rough sketch")])
def test_router_says_when_it_is_still_learning(monkeypatch: pytest.MonkeyPatch, days: int, phrase: str) -> None:
    _new_user(monkeypatch, days)
    r = agent.chat("can I afford $15 on 2026-11-07?", persona="maya", today=TODAY)
    assert phrase in r.reply


def test_confidence_note_is_grounded() -> None:
    r = tools.simulate_purchase(15, "2026-11-07", persona="maya", today=TODAY)
    assert agent.grounded(r["confidence_note"], "", r)


def test_a_thrown_away_reply_leaves_no_approvable_transfer_behind() -> None:
    before = set(tools.PENDING)
    fake = FakeGemini(_calls(("propose_transfer", {})), _text("Done, I moved $9,999 for you."))  # ungrounded
    r = agent.chat("fix it", persona="maya", client=fake, today=TODAY)
    new = set(tools.PENDING) - before
    assert r.pending_action is not None and new == {r.pending_action.id}  # only the router's proposal survives


def test_a_gemini_crash_after_proposing_leaves_nothing_behind() -> None:
    class Crashes(FakeGemini):
        def create(self, **kwargs: Any) -> SimpleNamespace:
            if self.sent:
                raise RuntimeError("quota")
            return super().create(**kwargs)

    before = set(tools.PENDING)
    with pytest.raises(RuntimeError):
        agent._chat_with_gemini(Crashes(_calls(("propose_transfer", {}))), "fix it", TODAY, "genz", "maya")
    assert set(tools.PENDING) == before

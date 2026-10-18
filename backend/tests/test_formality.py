"""The formality reader: it re-scores the trained model exactly, reads chat-style messages sensibly, and only
ever changes how Ask Runway speaks (the prompt), never what it says."""

import pytest

from app.agent import chat as agent
from app.agent import formality
from tests.test_agent import TODAY


def test_character_ngrams_match_scikit_learns_char_wb() -> None:
    # TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4)).build_analyzer()("hi  u"), from scikit-learn 1.9
    assert formality._char_ngrams("hi  u", 2, 4) == [" h", "hi", "i ", " hi", "hi ", " hi ", " u", "u ", " u "]


@pytest.mark.parametrize(
    ("message", "style"),
    [
        ("lol can i afford pizza tonight", "casual"),
        ("yo am i good for rent", "casual"),
        ("What is my balance?", "neutral"),
        ("Can I afford a $40 dinner?", "neutral"),
        ("Please transfer the necessary amount from my savings account.", "formal"),
        ("I would appreciate an overview of my spending by category.", "formal"),
        ("", "neutral"),
    ],
)
def test_reads_how_the_message_was_written(message: str, style: str) -> None:
    assert formality.read(message) == style


def test_a_plain_question_never_reads_formal_and_a_polite_one_never_reads_casual() -> None:
    assert formality.score("Kindly advise whether my grandson has repaid me.") > formality.score("pls fix it")


def test_the_prompt_carries_the_style_and_the_age(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    class Capture:
        class interactions:  # noqa: N801 — mimics the SDK's client.interactions
            @staticmethod
            def create(**kw):
                seen.append(kw["system_instruction"])
                raise RuntimeError("stop after the first request")

    monkeypatch.setattr(agent, "RETRY_DELAY_S", 0)
    agent.chat("lol am i broke", persona="sam", client=Capture(), today=TODAY)
    agent.chat("Could you please summarise my bills for the week?", persona="maya", client=Capture(), today=TODAY)
    assert (
        "How they wrote this message: casual (" in seen[0]
        and "their age, 60" in seen[0]
        and "sharp, warm financial assistant" in seen[0]
    )
    assert "How they wrote this message: formal (" in seen[-1] and "their age, 20" in seen[-1]


@pytest.mark.parametrize(
    ("voice", "style", "result"),
    [
        ("classic", "casual", "direct"),  # a 60-year-old writing "lol": one step, not a teenager's voice
        ("genz", "formal", "direct"),  # a 20-year-old writing formally: one step, not a bank letter
        ("genz", "casual", "genz"),  # already the most relaxed
        ("classic", "formal", "classic"),
        ("direct", "neutral", "direct"),  # a plain message: age decides
    ],
)
def test_age_picks_the_voice_and_a_clear_style_moves_it_one_step(voice, style, result) -> None:
    from app.agent import voice as voices

    assert voices.adjusted(voice, style) == result

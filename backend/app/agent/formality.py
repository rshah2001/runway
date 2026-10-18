"""How formally someone wrote their message, from a model trained on human ratings, so Ask Runway can meet
them where they are: a 55-year-old who types "lol can i afford pizza" gets a lighter reply, a 22-year-old
who writes "Could you please advise…" doesn't get slang.

The model (ml/formality_experiment.py) is character n-gram TF-IDF + ridge regression, trained on Pavlick &
Tetreault's 11k sentences rated -3 (very casual) to +3 (very formal), blended with a few chat cues the 2016
data lacks ("lol", "pls", a lowercase start). It's re-scored here in plain Python from
formality_model.json, exactly as scikit-learn would (the experiment checks that), so the server needs no ML
libraries and a message takes well under a millisecond. Held-out results are in ml/README.md.

The model only reads style. It never sees money, and it never changes what the answer says.
"""

import json
import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

Style = Literal["casual", "neutral", "formal"]
MODEL = Path(__file__).with_name("formality_model.json")
_SPACES = re.compile(r"\s\s+")


@lru_cache(maxsize=1)
def _model() -> dict[str, Any]:
    return json.loads(MODEL.read_text(encoding="utf-8"))


def _char_ngrams(text: str, low: int, high: int) -> list[str]:
    """scikit-learn's `char_wb` analyzer: n-grams inside words, each word padded with a space."""
    grams: list[str] = []
    for word in _SPACES.sub(" ", text).split():
        w = f" {word} "
        for n in range(low, high + 1):
            offset = 0
            grams.append(w[offset : offset + n])
            while offset + n < len(w):
                offset += 1
                grams.append(w[offset : offset + n])
            if offset == 0:  # a word shorter than n counts once
                break
    return grams


def _model_score(text: str, m: dict[str, Any]) -> float:
    """TF-IDF (sublinear tf, l2-normalised) dotted with the ridge coefficients."""
    counts: dict[str, int] = {}
    for g in _char_ngrams(text, *m["ngram_range"]):
        if g in m["terms"]:
            counts[g] = counts.get(g, 0) + 1
    weights = {g: (1 + math.log(c)) * m["terms"][g][0] for g, c in counts.items()}
    norm = math.sqrt(sum(v * v for v in weights.values())) or 1.0
    return m["intercept"] + sum(v / norm * m["terms"][g][1] for g, v in weights.items())


# Chat cues the forum-and-news training data rarely has. Kept small and named, so it's easy to argue with.
SLANG = re.compile(r"\b(lol|haha|omg|pls|plz|u|ur|gonna|wanna|yo|bruh|rn|tbh)\b", re.I)
CONTRACTION = re.compile(r"\b\w+'(s|t|re|ll|ve|d|m)\b")
POLITE = re.compile(r"\b(please|kindly|would|could|may i|regarding|therefore)\b", re.I)


def rules_score(text: str) -> float:
    """The hand-written part of the blend (and the experiment's no-learning baseline)."""
    score = -1.0 * bool(SLANG.search(text)) - 0.6 * bool(CONTRACTION.search(text))
    score -= 0.5 * text[:1].islower() + 0.5 * bool(re.search(r"[!?]{2,}", text))
    score += 0.6 * bool(POLITE.search(text)) + 0.3 * text.rstrip().endswith(".")
    return score + 0.02 * min(len(text.split()), 40)


def score(text: str) -> float:
    """Formality on the raters' scale, about -3 (very casual) to +3 (very formal)."""
    m = _model()
    blend = m["blend"]
    rules = (rules_score(text) - blend["rules_mean"]) / blend["rules_sd"] * blend["target_sd"]
    return (1 - blend["rules_weight"]) * _model_score(text, m) + blend["rules_weight"] * rules


def read(text: str) -> Style:
    """casual / neutral / formal. Neutral (a short "balance?") leaves the tone to the person's age."""
    m, s = _model(), score(text.strip())
    if not text.strip():
        return "neutral"
    return "casual" if s < m["casual_below"] else "formal" if s > m["formal_above"] else "neutral"

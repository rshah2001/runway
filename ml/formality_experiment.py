"""Train and test the formality reader that sets Ask Runway's tone from the person's own words.

Data: Pavlick & Tetreault (2016), 11,274 sentences from forums, blogs, emails and news, each rated by people
from -3 (very casual) to +3 (very formal); CC BY 3.0. `python ml/download.py formality` puts it in
ml/data/formality/. Scored on the 2,000 test sentences it never trains on, plus a small set of chat-style
money questions (CHAT below), because Runway's messages are short questions, not news sentences.

Writes backend/app/agent/formality_model.json: the vocabulary, idf weights and coefficients of the winner,
so the backend scores a message in plain Python (app/agent/formality.py) with no ML libraries.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_union

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "backend"))
from app.agent import formality  # noqa: E402 — the backend's scorer and rules: one source of truth

DATA = HERE / "data" / "formality"
OUT = HERE.parent / "backend" / "app" / "agent" / "formality_model.json"
RESULTS = HERE / "results_formality.csv"

# bands on the raters' own scale, for the test-set accuracy column
CASUAL_BELOW, FORMAL_ABOVE = -0.5, 0.5
# the bands Ask Runway acts on. Short chat questions score lower than the forum, email and news sentences the
# model learned from (in that data, questions mostly come from a casual forum), so a plain "What is my
# balance?" sits near -0.8. Set from CHAT below, then checked once on CHAT_HELDOUT, written afterwards.
# Anything in between is "neutral" and the tone stays with the person's age.
CHAT_CASUAL_BELOW, CHAT_FORMAL_ABOVE = -1.5, -0.2
# weight of the hand-written chat cues in the shipped blend. Chosen on the 20 CHAT questions below (the only
# chat-style text we have), so it's a sanity check, not a measurement; the test-set columns are honest
RULES_WEIGHT = 0.25

# Chat-style money questions, labelled by us (not by the dataset's raters): a sanity check that a model
# trained on forum and news sentences reads the kind of message Runway actually gets.
CHAT = [
    ("can i afford a $40 dinner tonight lol", "casual"),
    ("yo am i good for rent", "casual"),
    ("ugh how broke am i this week", "casual"),
    ("pls fix it", "casual"),
    ("wait did sam pay me back yet??", "casual"),
    ("ok send jordan 20 for gas", "casual"),
    ("lowkey scared to check my balance rn", "casual"),
    ("bruh why didnt i get help", "casual"),
    ("can i get those concert tix or nah", "casual"),
    ("whats my spending looking like haha", "casual"),
    ("Could you tell me whether I can afford a $40 dinner this evening?", "formal"),
    (
        "I would like to know if my account will remain above my cushion this month.",
        "formal",
    ),
    ("Please transfer the necessary amount from my savings account.", "formal"),
    ("Kindly advise whether my grandson has repaid the amount I provided.", "formal"),
    ("Would you be able to summarise my upcoming bills for the week?", "formal"),
    ("I wish to pause my support for Jordan, please.", "formal"),
    ("Could you please explain why I did not receive assistance?", "formal"),
    ("I would appreciate an overview of my spending by category.", "formal"),
    ("Please create a circle named Family and invite Emma.", "formal"),
    ("May I ask how much I could safely contribute to Maya?", "formal"),
]


# Written after the thresholds were fixed, labelled before scoring, evaluated once: casual, plain, formal.
CHAT_HELDOUT = [
    ("omg did my paycheck hit yet", "casual"),
    ("lol am i gonna make it to friday", "casual"),
    ("u think i can do sushi tmrw", "casual"),
    ("bro how much do i owe sam", "casual"),
    ("pls tell me i have money for gas", "casual"),
    ("haha ok whats my lowest day", "casual"),
    ("yo cover me for rent pls", "casual"),
    ("tbh idk where my money went", "casual"),
    ("can u make a circle for my roomies", "casual"),
    ("wanna send emma 15 bucks rn", "casual"),
    ("How much is in my checking account?", "plain"),
    ("When is my next paycheck?", "plain"),
    ("Can I afford new shoes on Saturday?", "plain"),
    ("Show me my subscriptions.", "plain"),
    ("Did anyone cover me this month?", "plain"),
    ("What bills are due this week?", "plain"),
    ("Ask Alex for $30.", "plain"),
    ("How much can I give Maya?", "plain"),
    ("Is my rent covered?", "plain"),
    ("Leave the Weekend crew circle.", "plain"),
    ("Could you let me know when my next salary deposit is expected?", "formal"),
    ("I would like a summary of my bills for the coming week, please.", "formal"),
    ("Please advise whether I am able to afford a purchase of $200.", "formal"),
    ("Would it be possible to repay my grandfather a portion of the amount?", "formal"),
    ("Kindly send fifty dollars to my daughter Emma.", "formal"),
    ("I should like to know whether anyone has repaid me.", "formal"),
    ("Could you please create a circle for my family members?", "formal"),
    (
        "I am concerned about my balance; would you review my upcoming expenses?",
        "formal",
    ),
    ("May I have an overview of my recurring charges?", "formal"),
    ("Please confirm whether my account will remain above my cushion.", "formal"),
]


def chat_bands(scores, labels) -> dict:
    """3-way accuracy on chat (plain should read neutral) and the costly flips (casual read formal or back)."""
    got = [
        "casual"
        if x < CHAT_CASUAL_BELOW
        else "formal"
        if x > CHAT_FORMAL_ABOVE
        else "neutral"
        for x in scores
    ]
    want = ["neutral" if lab == "plain" else lab for lab in labels]
    flips = sum({g, w} == {"casual", "formal"} for g, w in zip(got, want))
    return {
        "accuracy": sum(g == w for g, w in zip(got, want)) / len(want),
        "opposite": flips,
        "got": got,
    }


def load() -> tuple[pd.DataFrame, pd.DataFrame]:
    train, test = (
        pd.read_csv(DATA / f"{split}.csv").dropna() for split in ("train", "test")
    )
    return train, test


def rules_score(text: str) -> float:
    return formality.rules_score(text)


def band(score: float) -> str:
    return (
        "casual"
        if score < CASUAL_BELOW
        else "formal"
        if score > FORMAL_ABOVE
        else "neutral"
    )


def chat_accuracy(scores: list[float]) -> float:
    """Share of the chat questions put on the right side (a casual one must not read formal, and back)."""
    right = 0
    for (_, label), s in zip(CHAT, scores):
        right += (s < 0) if label == "casual" else (s > 0)
    return right / len(CHAT)


def word_vec(n_features: int) -> TfidfVectorizer:
    # case and punctuation kept: "LOL", "??" and a capital first letter are part of how formal it reads
    return TfidfVectorizer(
        lowercase=False,
        token_pattern=r"[A-Za-z']+|[!?.,]",
        ngram_range=(1, 2),
        max_features=n_features,
        sublinear_tf=True,
    )


def char_vec(n_features: int) -> TfidfVectorizer:
    return TfidfVectorizer(
        lowercase=False,
        analyzer="char_wb",
        ngram_range=(2, 4),
        max_features=n_features,
        sublinear_tf=True,
    )


def evaluate(
    name: str, pred_test: np.ndarray, test: pd.DataFrame, chat_scores: list[float]
) -> dict:
    rho = spearmanr(pred_test, test["avg_score"]).statistic
    bands_true = test["avg_score"].map(band)
    bands_pred = pd.Series(pred_test, index=test.index).map(band)
    # the costly mistake: reading a casual message as formal or the other way round
    flips = ((bands_true == "casual") & (bands_pred == "formal")) | (
        (bands_true == "formal") & (bands_pred == "casual")
    )
    row = {
        "model": name,
        "spearman_test": round(rho, 3),
        "band_accuracy_test": round((bands_true == bands_pred).mean(), 3),
        "opposite_band_test": round(flips.mean(), 3),
        "chat_side_accuracy": round(chat_accuracy(chat_scores), 3),
    }
    for domain, part in test.groupby("domain"):
        row[f"spearman_{domain}"] = round(
            spearmanr(
                pred_test[test.index.get_indexer(part.index)], part["avg_score"]
            ).statistic,
            3,
        )
    return row


def main() -> None:
    train, test = load()
    chat_text = [t for t, _ in CHAT]
    rows = []

    rules_test = np.array([rules_score(t) for t in test["sentence"]])
    rows.append(
        evaluate(
            "rules (no learning)", rules_test, test, [rules_score(t) for t in chat_text]
        )
    )

    candidates = {
        "words 1-2g + ridge (8k)": lambda: word_vec(8000),
        "chars 2-4g + ridge (8k)": lambda: char_vec(8000),
        "words + chars + ridge (8k+8k)": lambda: make_union(
            word_vec(8000), char_vec(8000)
        ),
        "words 1-2g + ridge (20k)": lambda: word_vec(20000),
    }
    fitted = {}
    for name, make in candidates.items():
        vec = make()
        x = vec.fit_transform(train["sentence"])
        model = Ridge(alpha=1.0).fit(x, train["avg_score"])
        pred = model.predict(vec.transform(test["sentence"]))
        chat = list(model.predict(vec.transform(chat_text)))
        rows.append(evaluate(name, pred, test, chat))
        fitted[name] = (vec, model, pred, np.array(chat))

    # the shipped blend: the character model plus a little of the chat cues, on the raters' scale
    vec, model, pred, chat = fitted["chars 2-4g + ridge (8k)"]
    r_train = np.array([rules_score(t) for t in train["sentence"]])
    blend = {
        "rules_weight": RULES_WEIGHT,
        "rules_mean": float(r_train.mean()),
        "rules_sd": float(r_train.std()),
        "target_sd": float(train["avg_score"].std()),
    }

    def mix(model_scores: np.ndarray, texts) -> np.ndarray:
        rules = (
            np.array([rules_score(t) for t in texts]) - blend["rules_mean"]
        ) / blend["rules_sd"]
        return (1 - RULES_WEIGHT) * model_scores + RULES_WEIGHT * rules * blend[
            "target_sd"
        ]

    shipped_test, shipped_chat = mix(pred, test["sentence"]), mix(chat, chat_text)
    rows.append(
        evaluate(
            f"SHIPPED: chars + {RULES_WEIGHT:.0%} chat cues",
            shipped_test,
            test,
            list(shipped_chat),
        )
    )

    table = pd.DataFrame(rows)
    table.to_csv(RESULTS, index=False)
    with pd.option_context("display.width", 200, "display.max_columns", 20):
        print(table.to_string(index=False))

    export(vec, model, blend)
    print(f"\nwrote {OUT.relative_to(HERE.parent)} ({OUT.stat().st_size // 1024} KB)")

    # the backend re-scores in plain Python: it must agree with scikit-learn on every held-out sentence
    formality._model.cache_clear()
    ours = np.array([formality.score(t) for t in test["sentence"]])
    gap = float(np.abs(ours - shipped_test).max())
    print(
        f"backend vs scikit-learn on {len(test)} test sentences: largest difference {gap:.2e}"
    )
    assert gap < 1e-3, "app/agent/formality.py no longer matches the trained model"
    held = chat_bands(
        [formality.score(t) for t, _ in CHAT_HELDOUT], [lab for _, lab in CHAT_HELDOUT]
    )
    print(
        f"held-out chat ({len(CHAT_HELDOUT)} messages, evaluated once): 3-way accuracy {held['accuracy']:.0%}, "
        f"casual<->formal flips {held['opposite']}"
    )
    for (t, lab), g in zip(CHAT_HELDOUT, held["got"]):
        if g != ("neutral" if lab == "plain" else lab):
            print(f"   miss: [{lab} -> {g}] {t}")


def export(vec: TfidfVectorizer, model: Ridge, blend: dict) -> None:
    terms = vec.get_feature_names_out()
    payload = {
        "source": "Pavlick & Tetreault (2016) formality ratings, CC BY 3.0; trained by ml/formality_experiment.py",
        "analyzer": "char_wb",
        "ngram_range": list(vec.ngram_range),
        "sublinear_tf": True,
        "intercept": round(float(model.intercept_), 6),
        "blend": blend,
        "casual_below": CHAT_CASUAL_BELOW,
        "formal_above": CHAT_FORMAL_ABOVE,
        # term -> [idf, coefficient]
        "terms": {
            t: [round(float(i), 5), round(float(c), 5)]
            for t, i, c in zip(terms, vec.idf_, model.coef_)
        },
    }
    OUT.write_text(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=False), encoding="utf-8"
    )


if __name__ == "__main__":
    main()

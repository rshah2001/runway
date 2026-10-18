# ML on real and realistic transaction data

Runway's forecast was built and tested on three seeded personas from our own generator, and a model
tested only on data you generated yourself proves little. This folder takes the forecast's two learned
parts — **how much you'll spend** and **how sure that is** — to outside data:

| Dataset | What it is | People | Years | Licence |
|---|---|---|---|---|
| [IBM TabFormer](https://github.com/IBM/TabFormer) | US card purchases from IBM's multi-agent simulation (synthetic, but not ours) | 1,573 with data since 2015 | 2015–20 | Apache-2.0 |
| [MoneyData](https://data.mendeley.com/datasets/dnxtg6n4rv/1) | One real, anonymised UK bank account | 1 | 2015–22 | CC BY 4.0 ¹ |
| [Berka / PKDD'99](https://relational.fel.cvut.cz/dataset/Financial) | Real Czech bank accounts | 4,500 | 1993–98 | public research dataset |

Everything is scored on **people the model never saw**: 20% of IBM users are held out, and MoneyData and
Berka are never trained on. Every feature is a ratio to the person's own spending, never an amount, so
crowns, pounds and dollars can be compared.

```bash
pip install -r ml/requirements.txt -r backend/requirements.txt
# Berka's read-only guest login is published on https://relational.fel.cvut.cz/dataset/Financial
export BERKA_DB_USER=… BERKA_DB_PASSWORD=…
python ml/download.py               # ~280 MB, into ml/data/ (git-ignored)
python ml/calibrate_band.py         # fits the range calibration -> backend/app/forecast/band_calibration.json
python ml/spend_model_experiment.py # the spending model we tried and did not ship
```

## 1. Shipped: calibrating the forecast's range (conformal)

Runway's range comes from a block bootstrap of the person's own days (`backend/app/forecast/band.py`).
Its cautious end — what the safety net plans on — should be beaten **5%** of the time. On outside data
it was beaten far more often:

| Cautious end beaten (target 5%) | 14 days of history | 30 | 60 | 90 |
|---|---|---|---|---|
| IBM, held-out users — before | 37% | 25% | 15% | 12% |
| IBM, held-out users — **after** | **5%** | **6%** | **5%** | **5%** |
| MoneyData (real, UK) — before | 43% | 28% | 17% | 14% |
| MoneyData (real, UK) — **after** | **7%** | **11%** | **8%** | **8%** |
| Berka (real, Czech, 1990s) — before | 29% | 41% | 18% | 15% |
| Berka (real, Czech, 1990s) — **after** | **6%** | 36% | **10%** | **9%** |

Coverage of the whole range (target 85%) goes from 33–82% before to 81–89% after, except Berka at 30
days (62%). Full table: `results_band.csv`.

**Why the bootstrap was overconfident.** Resampling a person's own days captures day-to-day noise, not
that some months simply cost more than others (a holiday, a car repair, a quiet month). With 14 days of
history it has seen at most two weeks of one level of spending.

**The fix: split conformal calibration.** For each training example, measure how many bootstrap spreads
the real next-30-day spending landed above the expected amount. The 95th percentile of that score, per
history length, is how much to widen the spread: ×3.3 at 30 days, ×2.0 at 60, ×1.6 at 90 (and ×1.7 / ×1.4
/ ×1.2 on the optimistic side). Each person keeps their own pattern; only the width is learned.

**Why this one, not a model that predicts the range directly.** A LightGBM quantile model of the range
was just as well calibrated on IBM users (4–7% beaten) but did worse on the real UK person (8–12%) and
was far too wide on Berka (about 1%): it had learned what IBM users look like. Widening the person's
own bootstrap transfers better because it only learns *how much* to widen.

**Checked beyond what it was fit for.** Fit at a 30-day horizon, it still holds at 14 days (beaten 3–9%,
a little cautious). Runway applies it at every horizon.

**Limits, said out loud.**
- Under 30 days of history the factor explodes (×180 at 14 days, because a two-week window can look
  perfectly steady). Runway uses the 30-day factor there and readiness already says "rough guide".
- Berka at 30 days stays badly calibrated: people there withdraw cash once or twice a month, so 30 days
  is one or two data points.
- Only one real modern person was available. IBM is realistic but synthetic.
- On Runway's own seeded personas the range is now wider than needed (91% coverage, 1% of days below
  the cautious end), because the generator draws every day independently — the one setting where a
  plain bootstrap is already right. We chose to calibrate to the outside data instead of our own.

## 2. Tried and not shipped: a model that predicts spending

A LightGBM model of "next-30-day spending ÷ the flat average's prediction", from ten features of the
person's recent days (how many days they spend, how lumpy it is, recent vs older, …). Error is total
absolute error as a share of total spending (lower is better), 90 days of history:

| | Flat average (Runway) | LightGBM |
|---|---|---|
| IBM held-out users (where it was trained) | 17.0% | **16.6%** |
| MoneyData (real, UK) | **56.2%** | 57.6% |
| Berka (real, Czech) | **68.6%** | 171.8% |
| Runway's seeded personas (balance error) | **$138** | $390 |

It wins by 2% where it was trained and loses everywhere else. The reason is visible in one feature:
IBM users spend on 96% of days (median), the real UK person on 50%, Runway's personas on ~30%, Berka's
1990s cash users on 4%. A tree model can't extrapolate past what it has seen, and these populations
barely overlap. An earlier version trained on Berka beat the flat average by 13–23% on held-out Berka
accounts — and failed on everything modern for the same reason in reverse.

So the forecast keeps the flat average, now with evidence from four populations rather than an
assumption. That's also why the shipped piece (section 1) calibrates the person's own pattern rather
than replacing it.

## 3. Shipped: reading how formally someone writes (for Ask Runway's tone)

Ask Runway starts from a voice for the person's age (Gen Z under 30, direct 30–49, courteous 50+), but age
is a guess about style, and the person's own message is evidence. A 60-year-old who types *"lol am i good
this month"* shouldn't get a bank letter; a 20-year-old who writes *"Could you please tell me…"* shouldn't
get slang. So a small model reads the message's formality, and Gemini is told the result as a fact, the
same way it's given every number by a tool.

**Data.** [Pavlick & Tetreault (2016)](https://huggingface.co/datasets/osyvokon/pavlick-formality-scores):
11,274 sentences from Yahoo Answers, blogs, emails and news, each rated by people from −3 (very casual) to +3
(very formal). CC BY 3.0. 9,274 train, 2,000 test, never trained on.

**What we didn't do, and why.** We didn't predict *age* from writing (the Blog Authorship Corpus has age
labels): we already know the user's age, guessing it from text is profiling, and how a 20-year-old blogged in
2004 says nothing about how they want to be spoken to. Formality is the one thing we need, and it's rated.

| Model (2,000 held-out sentences) | Rank correlation with people's ratings | Band accuracy | Casual read as formal, or back | Chat questions on the right side |
|---|---|---|---|---|
| Hand-written rules, no learning | 0.52 | 42% | 4.4% | 20/20 |
| Word 1–2-grams + ridge | 0.71 | 58% | 3.2% | 16/20 |
| Character 2–4-grams + ridge | **0.74** | 60% | 2.4% | 17/20 |
| Words + characters + ridge | 0.74 | 61% | 3.2% | 16/20 |
| **Shipped: characters + 25% chat cues** | **0.73** | 60% | 2.7% | **19/20** |

Per domain (shipped): emails 0.76, forum answers 0.67, blogs 0.63, news 0.43. News is hardest: nearly all of
it is formal, so there's little range to rank.

**The trap we found.** Every chat question the trained models got wrong was a *polite question* ("Could you
tell me whether I can afford…") read as casual. In the training data, questions come almost entirely from a
casual forum, so the model learned "question = casual". Two fixes:
- **A small blend with hand-written chat cues** ("lol", "pls", a lowercase start; "please", "would"), which
  the 2016 data barely contains: the held-out correlation stays at 0.73, and chat goes from 17/20 to 19/20.
  The 25% weight was chosen on those 20 chat questions (all the chat text we have), so treat 19/20 as a
  sanity check, not a measurement.
- **Chat thresholds.** Short questions score lower than the sentences the model learned from: a plain
  *"What is my balance?"* sits near −0.8 on the raters' scale. Ask Runway acts only on clear signals:
  **casual below −1.5, formal above −0.2**; anything in between is *neutral* and the tone stays with age.
  Set on the 20 questions above, then checked **once** on 30 new ones written afterwards (10 casual, 10
  plain, 10 formal): **30/30, no casual↔formal flips**. We wrote and labelled both sets ourselves, so this
  says the thresholds are sensible, not that they're precise.

**Shipping it like the range calibration.** No ML libraries in the server: the vocabulary, idf weights and
ridge coefficients go to `backend/app/agent/formality_model.json` (192 KB), and `app/agent/formality.py`
re-scores in plain Python. The experiment asserts it matches scikit-learn on all 2,000 test sentences
(largest difference 8×10⁻⁶). A message takes well under a millisecond, so Ask Runway gets no slower.

**Does it change what Gemini says?** On live Gemini, the same messages with the model's reading vs. with
every message read as neutral (age only), scored by the tone eval's plain rules:

| Writer | How they wrote | Age only (no model) | With the formality model |
|---|---|---|---|
| Sam, 60 (courteous voice) | casually ("lol am i good this month") | 0/12 | **9/12** |
| Maya, 20 (Gen Z voice) | formally ("Could you kindly list my subscriptions?") | 3/12 | **10/12** |
| **Both** | | **3/24 (13%)** | **19/24 (79%)** |

Four runs of three questions each, live Gemini, Oct 18. A reply passes if it reads the way they wrote:
contractions and none of the stiff phrases for Sam; no Gen Z words or emoji for Maya. The misses were a
reply that still opened "You are…" and one that said "Heads up" (which the tone eval counts as a Gen Z word).

**How it's used, and why that way.** Age always picks the voice first: it's the one thing known before
anyone writes. A clearly casual or formal message then moves the voice **one step** along Gen Z → direct →
courteous (`voice.adjusted`); a plain message leaves it where age put it. The first version only told Gemini
"lean more relaxed", and that lost to the courteous voice's own rules: 1/3 in a re-run. A firm one-step
switch is predictable and testable, and a 60-year-old who writes "lol" gets the direct voice, not a
teenager's.

## Files

| File | |
|---|---|
| `download.py` | fetches the datasets (checksum-verified where the source publishes one) |
| `samples.py` | loaders, the everyday-spending definition per dataset, the scale-free features |
| `calibrate_band.py` | fits and scores the conformal widening, writes `band_calibration.json` |
| `spend_model_experiment.py` | the LightGBM spending model and every comparison above |
| `formality_experiment.py` | trains and scores the formality reader, writes `formality_model.json`, checks the backend matches |
| `results_band.csv`, `results_spend_model.csv`, `results_formality.csv` | the full result tables |

¹ Firat, Vytla, Vasudeva, Jiang, Laramee. *MoneyVis: Open Bank Transaction Data for Visualization and
Beyond.* EuroVis 2023 Short Papers. https://doi.org/10.2312/evs.20231052

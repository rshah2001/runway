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

## Files

| File | |
|---|---|
| `download.py` | fetches the three datasets (checksum-verified where the source publishes one) |
| `samples.py` | loaders, the everyday-spending definition per dataset, the scale-free features |
| `calibrate_band.py` | fits and scores the conformal widening, writes `band_calibration.json` |
| `spend_model_experiment.py` | the LightGBM spending model and every comparison above |
| `results_band.csv`, `results_spend_model.csv` | the full result tables |

¹ Firat, Vytla, Vasudeva, Jiang, Laramee. *MoneyVis: Open Bank Transaction Data for Visualization and
Beyond.* EuroVis 2023 Short Papers. https://doi.org/10.2312/evs.20231052

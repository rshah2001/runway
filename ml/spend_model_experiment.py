"""Could a trained model predict next month's everyday spending better than Runway's flat average?

A LightGBM quantile model of the ratio "next-30-day spending ÷ 30 × the history's daily mean", from ten
scale-free features of the person's recent days (ml/samples.py). Trained on 80% of IBM card users,
scored on the other 20%, on MoneyData and Berka without retraining, and on Runway's own backtest.

Result (ml/README.md): it barely beats the flat average where it was trained and loses everywhere
else, because spending habits in the other datasets fall outside anything it saw. So Runway keeps the
flat average; this script stays as the evidence for that decision.

Run from the repo root (after ml/download.py):  python ml/spend_model_experiment.py
"""

import os
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import samples

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "ml" / "data"
os.environ.setdefault("RUNWAY_FORCE_MOCK", "1")
sys.path.insert(0, str(ROOT / "backend"))
from app.forecast.spend_model import SpendProfile, daily_totals, fit_flat  # noqa: E402
from evals import forecast_backtest  # noqa: E402

FEATURES = [
    "history_days", "spend_day_share", "daily_cv", "weekly_cv", "top_day_share", "median_spend_day",
    "last7_vs_mean", "last14_vs_mean", "first_half_vs_second", "days_since_spend",
]  # fmt: skip
PARAMS = dict(
    objective="quantile", alpha=0.5, n_estimators=300, learning_rate=0.03, num_leaves=15,
    min_child_samples=100, subsample=0.8, subsample_freq=1, colsample_bytree=0.8, verbose=-1,
)  # fmt: skip
SEED = 0


def wape(pred: pd.Series, actual: pd.Series) -> float:
    """Total absolute error as a share of total actual spending."""
    return float((pred - actual).abs().sum() / actual.sum())


def score(name: str, df: pd.DataFrame, model: lgb.LGBMRegressor) -> list[dict]:
    df = df.assign(ml=model.predict(df[FEATURES]) * df["flat_mean_30"])
    return [
        {
            "dataset": name,
            "history_days": h,
            "examples": len(g),
            "error_flat_average": wape(g.flat_mean_30, g.future_30),
            "error_lightgbm": wape(g.ml, g.future_30),
        }
        for h, g in df.groupby("history_days")
    ]


def on_runway_personas(model: lgb.LGBMRegressor) -> pd.DataFrame:
    """Runway's own backtest, with the model as one more spend method."""

    def fit_model(outflows, start, end) -> SpendProfile:
        window = np.array(daily_totals(outflows, start, end))
        if len(window) < 14 or window.sum() <= 0:
            return fit_flat(outflows, start, end)
        ratio = float(model.predict(pd.DataFrame([samples.features(window, min(len(window), 90))])[FEATURES])[0])
        return SpendProfile((window.mean() * ratio,) * 7)

    forecast_backtest.METHODS["LightGBM (trained on IBM)"] = fit_model
    return forecast_backtest.run()


def main() -> None:
    ibm = samples.build(*samples.load_ibm(str(DATA / "ibm" / "card_transaction.v1.csv")))
    people = ibm.person.unique()
    held_out = set(np.random.default_rng(SEED).choice(people, size=len(people) // 5, replace=False))
    train, test = ibm[~ibm.person.isin(held_out)], ibm[ibm.person.isin(held_out)]
    model = lgb.LGBMRegressor(**PARAMS).fit(train[FEATURES], train["ratio"])

    rows = score("IBM held-out users (synthetic, US card)", test, model)
    money = samples.build(*samples.load_moneydata(str(DATA / "moneydata" / "moneydata.xlsx")), step=7)
    rows += score("MoneyData (real, UK 2015-22, 1 person)", money, model)
    rows += score("Berka (real, Czech 1993-98)", samples.build(*samples.load_berka(str(DATA / "berka"))), model)
    results = pd.DataFrame(rows)
    pd.set_option("display.width", 200)
    print(results.round(3).to_string(index=False))
    results.to_csv(ROOT / "ml" / "results_spend_model.csv", index=False)

    print("\nWhy it doesn't transfer: share of days with any spending (5th / 50th / 95th percentile)")
    for name, df in [("IBM training users", train), ("MoneyData", money)]:
        print(f"  {name}: {df.spend_day_share.quantile([0.05, 0.5, 0.95]).round(2).tolist()}")
    print("\nOn Runway's seeded personas:\n" + forecast_backtest.table(on_runway_personas(model)))


if __name__ == "__main__":
    main()

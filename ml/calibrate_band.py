"""Conformal calibration of Runway's forecast range, fit on IBM card users, tested on real data.

Runway's range (backend/app/forecast/band.py) bootstraps a person's own daily spending. That captures
day-to-day noise but not month-to-month swings in the level of spending, so on real and realistic data
its cautious end is beaten far more often than the 5% it promises. Split conformal calibration fixes
that without replacing the person's own pattern: for each held-in example, measure how many bootstrap
spreads the real next-30-day spending landed above (or below) the expected amount; the 95th (90th)
percentile of that score, per history length, is the factor to widen the spread by.

Fit on 80% of IBM users; scored on the other 20% and on two datasets it never saw (MoneyData, Berka).
Writes backend/app/forecast/band_calibration.json, which band.py reads.

Run from the repo root (after ml/download.py):  python ml/calibrate_band.py
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import samples

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "ml" / "data"
OUT = ROOT / "backend" / "app" / "forecast" / "band_calibration.json"
sys.path.insert(0, str(ROOT / "backend"))
from app.forecast import band  # noqa: E402  the live bootstrap, before calibration

SHIPPED_HISTORIES = [30, 60, 90]  # under 30 days the factor explodes (see README); readiness says "rough guide"
EXAMPLES_PER_HISTORY = 2500
SEED = 0


def scored(df: pd.DataFrame, horizon: int = 30) -> pd.DataFrame:
    """Each example's conformity scores: how many raw bootstrap spreads the real future landed above the
    expected amount (cautious side) or below it (optimistic side)."""
    df = pd.concat(
        g.sample(n=min(EXAMPLES_PER_HISTORY, len(g)), random_state=SEED) for _, g in df.groupby("history_days")
    )
    spreads = [band.raw_spread(tuple(float(x) for x in w), horizon)[horizon - 1] for w in df["window"]]
    expected = df["flat_mean_30"] / 30 * horizon
    future = df[f"future_{horizon}"]
    down = np.array([s[0] for s in spreads]).clip(min=1e-9)
    up = np.array([s[1] for s in spreads]).clip(min=1e-9)
    return df.assign(score_hi=(future - expected) / down, score_lo=(expected - future) / up)


def fit(train: pd.DataFrame) -> pd.DataFrame:
    s = scored(train)
    return pd.DataFrame(
        {
            "cautious": s.groupby("history_days").score_hi.quantile(band.SPEND_QUANTILE_FOR_LOW_BALANCE),
            "optimistic": s.groupby("history_days").score_lo.quantile(1 - band.SPEND_QUANTILE_FOR_HIGH_BALANCE),
        }
    ).clip(lower=1.0)  # calibration only ever widens: never claim more certainty than the bootstrap


def evaluate(name: str, df: pd.DataFrame, factors: pd.DataFrame, horizon: int = 30) -> list[dict]:
    s = scored(df, horizon).join(factors, on="history_days")
    rows = []
    for h, g in s.groupby("history_days"):
        rows.append(
            {
                "dataset": name,
                "horizon": horizon,
                "history_days": h,
                "examples": len(g),
                "beaten_before": (g.score_hi > 1).mean(),
                "beaten_after": (g.score_hi > g.cautious).mean(),
                "coverage_before": ((g.score_hi <= 1) & (g.score_lo <= 1)).mean(),
                "coverage_after": ((g.score_hi <= g.cautious) & (g.score_lo <= g.optimistic)).mean(),
            }
        )
    return rows


def main() -> None:
    ibm = samples.build(*samples.load_ibm(str(DATA / "ibm" / "card_transaction.v1.csv")))
    people = ibm.person.unique()
    held_out = set(np.random.default_rng(SEED).choice(people, size=len(people) // 5, replace=False))
    train, test = ibm[~ibm.person.isin(held_out)], ibm[ibm.person.isin(held_out)]
    factors = fit(train)
    print("Widening factors (fit on IBM training users):\n" + factors.round(2).to_string())

    ibm_name, money_name = "IBM held-out users (synthetic, US card)", "MoneyData (real, UK 2015-22, 1 person)"
    money = samples.build(*samples.load_moneydata(str(DATA / "moneydata" / "moneydata.xlsx")), step=7)
    berka = samples.build(*samples.load_berka(str(DATA / "berka")))
    rows = evaluate(ibm_name, test, factors)
    rows += evaluate(money_name, money, factors)
    rows += evaluate("Berka (real, Czech 1993-98, 4,500 accounts)", berka, factors)
    # fit at a 30-day horizon; check it still holds at 14 days, since Runway applies it at every horizon
    rows += evaluate(ibm_name, test, factors, horizon=14)
    rows += evaluate(money_name, money, factors, horizon=14)
    results = pd.DataFrame(rows)
    pd.set_option("display.width", 220)
    print(results.round(3).to_string(index=False))

    shipped = factors.loc[SHIPPED_HISTORIES]
    OUT.write_text(
        json.dumps(
            {
                "method": "split conformal widening of the bootstrap spread at a 30-day horizon",
                "fit_on": f"IBM TabFormer, {len(train.person.unique())} training users, 2015 onward",
                "history_days": SHIPPED_HISTORIES,
                "cautious": [round(float(x), 3) for x in shipped.cautious],
                "optimistic": [round(float(x), 3) for x in shipped.optimistic],
            },
            indent=2,
        )
        + "\n"
    )
    results.to_csv(ROOT / "ml" / "results_band.csv", index=False)
    print(f"\nwrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

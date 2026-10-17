"""Turn transaction datasets into (history window -> next 30 days of everyday spending) samples.

Everyday spending = money a person spends day to day: card purchases and cash, not rent, bills,
standing orders or savings. Same idea as Runway's `everyday_outflows`. Each loader returns one row
per (person, day) with spending, plus each person's first and last day of data.

Every feature is a ratio to the person's own spending rate, never an amount, so a model trained on
one currency or era can be scored on another.
"""

import numpy as np
import pandas as pd

HORIZON = 30
HISTORIES = [14, 30, 60, 90]
FIXED_SYMBOLS = {"SIPO", "POJISTNE", "UVER", "LEASING", "SLUZBY", "SANKC. UROK"}


# ---------- loaders: each returns (daily spend rows, per-person span) ----------


def load_berka(data_dir: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Czech bank, 1993–98, real. Everyday = cash, card, one-off transfers; not standing orders or fees."""
    t = pd.read_csv(f"{data_dir}/trans.csv", parse_dates=["date"], low_memory=False)
    o = pd.read_csv(f"{data_dir}/order.csv")
    standing = set(zip(o.account_id, o.bank_to.astype(str), o.account_to.astype(str), strict=True))
    out = t[t.type.isin(["VYDAJ", "VYBER"])].copy()
    out = out[~out.k_symbol.fillna("").str.strip().isin(FIXED_SYMBOLS)]
    key = list(
        zip(out.account_id, out.bank.astype(str), out.account.fillna(0).astype("int64").astype(str), strict=True)
    )
    out = out[[k not in standing for k in key]]
    daily = out.groupby(["account_id", "date"]).amount.sum().rename("spend").reset_index()
    span = t.groupby("account_id").date.agg(["min", "max"])
    return daily.rename(columns={"account_id": "person"}), span.rename_axis("person")


def load_ibm(csv_path: str, since: str = "2015-01-01") -> tuple[pd.DataFrame, pd.DataFrame]:
    """IBM TabFormer, US card purchases, synthetic (multi-agent simulation). Refunds and fraud left out."""
    cols = ["User", "Year", "Month", "Day", "Amount", "Is Fraud?"]
    t = pd.read_csv(csv_path, usecols=cols)
    t["date"] = pd.to_datetime(dict(year=t.Year, month=t.Month, day=t.Day))
    t = t[t.date >= since]
    t["amount"] = t.Amount.str.replace("$", "", regex=False).astype(float)
    span = t.groupby("User").date.agg(["min", "max"])
    t = t[(t.amount > 0) & (t["Is Fraud?"] == "No")]
    daily = t.groupby(["User", "date"]).amount.sum().rename("spend").reset_index()
    return daily.rename(columns={"User": "person"}), span.rename_axis("person")


def load_moneydata(xlsx_path: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """MoneyData, one UK person, 2015–22, real. Everyday = debit-card purchases and cash withdrawals."""
    t = pd.read_excel(xlsx_path, sheet_name=0)
    t["date"] = pd.to_datetime(t["Transaction Date"], dayfirst=True)
    span = pd.DataFrame({"min": [t.date.min()], "max": [t.date.max()]}, index=pd.Index([1], name="person"))
    out = t[t["Transaction Type"].isin(["DEB", "CPT"]) & t["Debit Amount"].notna()]
    daily = out.groupby("date")["Debit Amount"].sum().rename("spend").reset_index()
    daily.insert(0, "person", 1)
    return daily, span


# ---------- features and samples ----------


def features(window: np.ndarray, history_days: int) -> dict[str, float]:
    """Scale-free description of a history window of daily spending (zeros included)."""
    mean = window.mean()
    spend_days = (window > 0).sum()
    weekly = window[: len(window) // 7 * 7].reshape(-1, 7).sum(axis=1)
    half = len(window) // 2
    return {
        "history_days": history_days,
        "spend_day_share": spend_days / len(window),
        "daily_cv": window.std() / mean,
        "weekly_cv": weekly.std() / weekly.mean() if weekly.mean() else 0.0,
        "top_day_share": window.max() / window.sum(),
        "median_spend_day": float(np.median(window[window > 0])) / mean,
        "last7_vs_mean": window[-7:].mean() / mean,
        "last14_vs_mean": window[-14:].mean() / mean,
        "first_half_vs_second": window[:half].mean() / max(window[half:].mean(), 1e-9),
        "days_since_spend": int(len(window) - 1 - np.flatnonzero(window > 0)[-1]),
    }


def build(daily: pd.DataFrame, span: pd.DataFrame, step: int = 30) -> pd.DataFrame:
    """Samples for every person, cutoff and history length. `ratio` is the target: next-30-day spend
    divided by 30 × the window's daily mean (1.0 = "the flat mean was exactly right")."""
    rows = []
    for person, g in daily.groupby("person"):
        days = pd.date_range(span.loc[person, "min"], span.loc[person, "max"])
        series = g.set_index("date").spend.reindex(days, fill_value=0.0).to_numpy()
        for cut in range(max(HISTORIES), len(series) - HORIZON, step):
            future = series[cut : cut + HORIZON].sum()
            future_14 = series[cut : cut + 14].sum()  # to check a 30-day calibration holds at other horizons
            for h in HISTORIES:
                window = series[cut - h : cut]
                if window.sum() <= 0:
                    continue  # no spending seen yet: nothing to scale from (Runway shows no rate either)
                rows.append(
                    {
                        "person": person,
                        "cutoff": days[cut],
                        **features(window, h),
                        "flat_mean_30": window.mean() * HORIZON,
                        "last30_30": series[cut - 30 : cut].sum() if h >= 30 else np.nan,
                        "future_30": future,
                        "future_14": future_14,
                        "ratio": future / (window.mean() * HORIZON),
                        "window": window,
                    }
                )
    return pd.DataFrame(rows)

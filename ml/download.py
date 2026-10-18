"""Download the public datasets the ML experiments use into ml/data/ (git-ignored).

  * Berka (PKDD'99): 4,500 real Czech bank accounts, 1993–98. Public CTU relational repository.
  * IBM TabFormer: 24M synthetic US card transactions from a multi-agent simulation. Apache-2.0.
  * MoneyData: one real, anonymised UK bank account, 2015–22. CC BY 4.0 (cite Firat et al., EuroVis 2023).
  * Formality: 11,274 sentences rated -3 (casual) to +3 (formal) by people (Pavlick & Tetreault, TACL 2016;
    Lahiri 2015). CC BY 3.0. For Ask Runway's tone, not the forecast.

Run from the repo root:  python ml/download.py [berka] [ibm] [moneydata] [formality]   (default: all)
"""

import hashlib
import os
import sys
import tarfile
import urllib.request
from pathlib import Path

DATA = Path(__file__).parent / "data"
IBM_URL = "https://media.githubusercontent.com/media/IBM/TabFormer/main/data/credit_card/transactions.tgz"
IBM_MEMBER = "card_transaction.v1.csv"
MONEYDATA_URL = (
    "https://data.mendeley.com/public-files/datasets/dnxtg6n4rv/files/"
    "36b3d359-2491-4282-850f-3f03e00fbfe3/file_downloaded"
)
MONEYDATA_SHA256 = "716eaf9ad4a3cf60dc9c9c8a20ed9a917c545a1b5f139f40ed91d2104faa3ff7"
FORMALITY_URL = "https://huggingface.co/datasets/osyvokon/pavlick-formality-scores/resolve/main/{split}.csv"
FORMALITY_SHA256 = {
    "train": "aa7449874891d139db8accfa6913502c5a8df9c134dfeb7d8421bf7709f8ae8d",
    "test": "43873f898de5e9721b9a8f93da931aad97ef9f188ff7ae6c0753f0a5f588339e",
}
BERKA_TABLES = ["account", "order", "trans"]
BERKA_HOST = "relational.fel.cvut.cz"
BERKA_PAGE = "https://relational.fel.cvut.cz/dataset/Financial"


def berka() -> None:
    # The repository's public, read-only guest login is published on BERKA_PAGE. It's read from the
    # environment rather than written here, so no credential, even a public one, lives in the code.
    user, password = os.getenv("BERKA_DB_USER"), os.getenv("BERKA_DB_PASSWORD")
    if not (user and password):
        raise SystemExit(
            f"Set BERKA_DB_USER and BERKA_DB_PASSWORD to the guest login listed on {BERKA_PAGE}"
        )
    import pandas as pd
    import pymysql

    out = DATA / "berka"
    out.mkdir(parents=True, exist_ok=True)
    conn = pymysql.connect(
        host=BERKA_HOST, port=3306, user=user, password=password, database="financial"
    )
    for table in BERKA_TABLES:
        df = pd.read_sql(f"SELECT * FROM `{table}`", conn)
        df.to_csv(out / f"{table}.csv", index=False)
        print(f"berka/{table}.csv: {len(df):,} rows")


def ibm() -> None:
    out = DATA / "ibm"
    out.mkdir(parents=True, exist_ok=True)
    archive = out / "transactions.tgz"
    if not archive.exists():
        print("downloading IBM TabFormer (279 MB)…")
        urllib.request.urlretrieve(IBM_URL, archive)
    with tarfile.open(archive) as tar:
        member = tar.getmember(
            IBM_MEMBER
        )  # extract only the one expected file, never arbitrary paths
        tar.extract(member, out, filter="data")
    print(f"ibm/{IBM_MEMBER}: extracted")


def moneydata() -> None:
    out = DATA / "moneydata"
    out.mkdir(parents=True, exist_ok=True)
    path = out / "moneydata.xlsx"
    urllib.request.urlretrieve(MONEYDATA_URL, path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != MONEYDATA_SHA256:
        raise SystemExit(f"moneydata.xlsx checksum mismatch: {digest}")
    print("moneydata/moneydata.xlsx: checksum ok")


def formality() -> None:
    out = DATA / "formality"
    out.mkdir(parents=True, exist_ok=True)
    for split, expected in FORMALITY_SHA256.items():
        path = out / f"{split}.csv"
        urllib.request.urlretrieve(FORMALITY_URL.format(split=split), path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != expected:
            raise SystemExit(f"formality/{split}.csv checksum mismatch: {digest}")
        print(f"formality/{split}.csv: checksum ok")


if __name__ == "__main__":
    steps = {"berka": berka, "ibm": ibm, "moneydata": moneydata, "formality": formality}
    for name in sys.argv[1:] or list(steps):
        steps[name]()

"""Download the three public datasets the ML experiments use into ml/data/ (git-ignored).

  * Berka (PKDD'99): 4,500 real Czech bank accounts, 1993–98. Public CTU relational repository.
  * IBM TabFormer: 24M synthetic US card transactions from a multi-agent simulation. Apache-2.0.
  * MoneyData: one real, anonymised UK bank account, 2015–22. CC BY 4.0 (cite Firat et al., EuroVis 2023).

Run from the repo root:  python ml/download.py [berka] [ibm] [moneydata]   (default: all three)
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
BERKA_TABLES = ["account", "order", "trans"]
BERKA_HOST = "relational.fel.cvut.cz"
BERKA_PAGE = "https://relational.fel.cvut.cz/dataset/Financial"


def berka() -> None:
    # The repository's public, read-only guest login is published on BERKA_PAGE. It's read from the
    # environment rather than written here, so no credential, even a public one, lives in the code.
    user, password = os.getenv("BERKA_DB_USER"), os.getenv("BERKA_DB_PASSWORD")
    if not (user and password):
        raise SystemExit(f"Set BERKA_DB_USER and BERKA_DB_PASSWORD to the guest login listed on {BERKA_PAGE}")
    import pandas as pd
    import pymysql

    out = DATA / "berka"
    out.mkdir(parents=True, exist_ok=True)
    conn = pymysql.connect(host=BERKA_HOST, port=3306, user=user, password=password, database="financial")
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
        member = tar.getmember(IBM_MEMBER)  # extract only the one expected file, never arbitrary paths
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


if __name__ == "__main__":
    wanted = sys.argv[1:] or ["berka", "ibm", "moneydata"]
    for name in wanted:
        {"berka": berka, "ibm": ibm, "moneydata": moneydata}[name]()

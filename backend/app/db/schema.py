"""Tiger Data schema. Idempotent — runs on every API start and before every seed.

Why TimescaleDB features, not plain Postgres tables:
  * `transactions` is a hypertable: every query here is "this customer, this time range", which
    is exactly what time-partitioned chunks make fast.
  * `daily_spend` is a continuous aggregate: per-day, per-category spend is precomputed and kept
    fresh by a policy, so the Spending screen and the forecast never re-scan raw purchases.
    `materialized_only = false` (real-time aggregation) means purchases made minutes ago show up
    before the next refresh.
  * Older chunks are compressed (columnstore), segmented by customer.
"""

import logging

import psycopg

log = logging.getLogger(__name__)

TABLES = """
CREATE TABLE IF NOT EXISTS personas (
    slug         text PRIMARY KEY,
    first_name   text NOT NULL,
    story        text NOT NULL,
    customer_id  text NOT NULL UNIQUE,
    checking_id  text NOT NULL,
    savings_id   text NOT NULL,
    credit_id    text NOT NULL,
    seeded_at    timestamptz NOT NULL DEFAULT now()
);

-- Nessie never updates balances, so the live balance = opening_balance + transactions since opening_at.
CREATE TABLE IF NOT EXISTS accounts (
    id               text PRIMARY KEY,
    customer_id      text NOT NULL,
    type             text NOT NULL CHECK (type IN ('Checking', 'Savings', 'Credit Card')),
    nickname         text NOT NULL,
    opening_balance  numeric(12, 2) NOT NULL,
    opening_at       timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS merchants (
    id        text PRIMARY KEY,
    name      text NOT NULL,
    category  text NOT NULL
);

-- upcoming scheduled outflows: the forecast's main input
CREATE TABLE IF NOT EXISTS bills (
    id                 text PRIMARY KEY,
    account_id         text NOT NULL,
    customer_id        text NOT NULL,
    payee              text NOT NULL,
    nickname           text NOT NULL,
    amount             numeric(12, 2) NOT NULL,
    recurring_day      int,
    status             text NOT NULL,
    next_payment_date  date
);

CREATE TABLE IF NOT EXISTS transactions (
    ts           timestamptz NOT NULL,
    nessie_id    text NOT NULL,
    account_id   text NOT NULL,
    customer_id  text NOT NULL,
    kind         text NOT NULL CHECK (kind IN ('purchase', 'deposit', 'withdrawal', 'transfer', 'bill')),
    amount       numeric(12, 2) NOT NULL,  -- signed, from the account's point of view: negative = money out
    merchant_id  text,
    category     text,
    description  text,
    status       text NOT NULL,
    PRIMARY KEY (nessie_id, ts)            -- hypertable unique keys must include the time column
);
"""

HYPERTABLE = """
SELECT create_hypertable('transactions', by_range('ts', INTERVAL '7 days'), if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS transactions_customer_ts ON transactions (customer_id, ts DESC);
CREATE INDEX IF NOT EXISTS transactions_account_ts ON transactions (account_id, ts DESC);
"""

DAILY_SPEND = """
CREATE MATERIALIZED VIEW IF NOT EXISTS daily_spend
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT time_bucket(INTERVAL '1 day', ts) AS day,
       customer_id,
       category,
       sum(-amount)  AS spent,
       count(*)      AS purchases
FROM transactions
WHERE kind = 'purchase' AND status = 'completed'
GROUP BY day, customer_id, category
WITH NO DATA;
"""

POLICIES = """
SELECT add_continuous_aggregate_policy('daily_spend',
    start_offset => INTERVAL '400 days', end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '15 minutes', if_not_exists => TRUE);
"""

COMPRESSION = """
ALTER TABLE transactions SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'customer_id',
    timescaledb.compress_orderby = 'ts DESC'
);
SELECT add_compression_policy('transactions', INTERVAL '180 days', if_not_exists => TRUE);
"""


def apply(conn: psycopg.Connection) -> None:
    """Create or update every table, the hypertable, the continuous aggregate and its policies."""
    conn.autocommit = True  # continuous-aggregate DDL cannot run inside a transaction block
    try:
        conn.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
        for block in (TABLES, HYPERTABLE, DAILY_SPEND, POLICIES):
            conn.execute(block)
        enabled = conn.execute(
            "SELECT compression_enabled FROM timescaledb_information.hypertables WHERE hypertable_name = 'transactions'"
        ).fetchone()
        if enabled and not list(enabled.values())[0]:
            conn.execute(COMPRESSION)
    finally:
        conn.autocommit = False
    log.info("schema applied")


def refresh_daily_spend(conn: psycopg.Connection) -> None:
    """Materialize the aggregate now (the policy also does this every 15 minutes)."""
    conn.autocommit = True
    try:
        conn.execute("CALL refresh_continuous_aggregate('daily_spend', NULL, NULL)")
    finally:
        conn.autocommit = False

"""Tiger Data schema. Idempotent — runs on every API start and before every seed.

Why TimescaleDB features, not plain Postgres tables:
  * `transactions` is a hypertable: every query here is "this customer, this time range", which
    is exactly what time-partitioned chunks make fast.
  * `daily_spend` is a continuous aggregate: per-day, per-category spend is precomputed and kept
    fresh by a policy, so the Spending screen and the forecast never re-scan raw purchases.
    `materialized_only = false` (real-time aggregation) means purchases made minutes ago show up
    before the next refresh.
  * Older chunks are compressed (columnstore), segmented by customer.
  * `forecast_snapshots` is a hypertable of every forecast Runway showed, one row per (persona, day it
    was made, day it was for), later scored against the real end-of-day balance; the
    `forecast_accuracy_daily` continuous aggregate rolls those scores up into the report card.
"""

import logging

import psycopg

from app.forecast.snapshots import TRACKED_LEADS

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

# peer-to-peer: Nessie has no P2P (transfers carry no payee), so Runway models it — every payment
# is a real Nessie transfer on the sender's account + a deposit on the receiver's, both ids kept here
P2P = """
ALTER TABLE personas ADD COLUMN IF NOT EXISTS age int;

CREATE TABLE IF NOT EXISTS contacts (
    id            text PRIMARY KEY,                -- "<persona>-<key>", e.g. "maya-alex"
    persona_slug  text NOT NULL REFERENCES personas (slug) ON DELETE CASCADE,
    first_name    text NOT NULL,
    last_name     text NOT NULL,
    relation      text NOT NULL,
    customer_id   text NOT NULL,                   -- a real Nessie customer…
    checking_id   text NOT NULL                    -- …with a real Nessie checking account
);

CREATE TABLE IF NOT EXISTS p2p_payments (
    id                  text PRIMARY KEY,
    persona_slug        text NOT NULL,
    contact_id          text NOT NULL REFERENCES contacts (id) ON DELETE CASCADE,
    direction           text NOT NULL CHECK (direction IN ('in', 'out')),  -- in = contact paid the persona
    amount              numeric(12, 2) NOT NULL CHECK (amount > 0),
    memo                text NOT NULL,
    ts                  timestamptz NOT NULL,
    sender_nessie_id    text NOT NULL,             -- transfer on the sender's account
    receiver_nessie_id  text NOT NULL              -- deposit on the receiver's account
);
CREATE INDEX IF NOT EXISTS p2p_payments_persona_ts ON p2p_payments (persona_slug, ts DESC);

CREATE TABLE IF NOT EXISTS p2p_requests (
    id            text PRIMARY KEY,
    persona_slug  text NOT NULL,
    contact_id    text NOT NULL REFERENCES contacts (id) ON DELETE CASCADE,
    amount        numeric(12, 2) NOT NULL CHECK (amount > 0),  -- the contact owes the persona this
    memo          text NOT NULL,
    status        text NOT NULL CHECK (status IN ('open', 'settling', 'paid', 'declined', 'failed')),
    created_at    timestamptz NOT NULL DEFAULT now(),
    settled_at    timestamptz,
    payment_id    text REFERENCES p2p_payments (id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS p2p_requests_persona ON p2p_requests (persona_slug, status);
"""

# family safety net: lenders pre-authorize bridges up to a limit; the agent covers a forecast dip
# automatically under the limit, asks for an Auth0 push approval over it, and repays on payday
# what each person wants to keep in checking (app/prefs.py); no row = the default cushion
MONEY_PREFS = """
CREATE TABLE IF NOT EXISTS money_preferences (
    slug        text PRIMARY KEY REFERENCES personas (slug) ON DELETE CASCADE,
    safe_floor  numeric(12, 2) NOT NULL CHECK (safe_floor >= 0 AND safe_floor <= 5000),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
"""

SAFETY_NET = """
CREATE TABLE IF NOT EXISTS safety_limits (
    lender_slug    text NOT NULL REFERENCES personas (slug) ON DELETE CASCADE,
    borrower_slug  text NOT NULL REFERENCES personas (slug) ON DELETE CASCADE,
    limit_amount   numeric(12, 2) NOT NULL CHECK (limit_amount >= 0),  -- set by the LENDER only
    enabled        boolean NOT NULL DEFAULT true,
    updated_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (lender_slug, borrower_slug),
    CHECK (lender_slug <> borrower_slug)
);

CREATE TABLE IF NOT EXISTS bridges (
    id                 text PRIMARY KEY,
    borrower_slug      text NOT NULL,
    lender_slug        text NOT NULL,
    amount             numeric(12, 2) NOT NULL CHECK (amount > 0),
    reason             text NOT NULL,
    status             text NOT NULL CHECK (status IN ('pending_approval', 'declined', 'funding', 'active',
                                                   'repaying', 'repaid', 'repay_failed', 'failed')),
    mode               text NOT NULL CHECK (mode IN ('auto', 'approval')),  -- auto = under the lender's limit
    shortfall_date     date NOT NULL,
    due_date           date NOT NULL,           -- the borrower's next payday
    created_at         timestamptz NOT NULL DEFAULT now(),
    funded_at          timestamptz,
    repaid_at          timestamptz,
    approval_channel   text,                    -- 'auth0_push' | 'in_app'
    auth_req_id        text,                    -- Auth0 CIBA request id while waiting for the push
    out_transfer_id    text, out_deposit_id    text,   -- lender → borrower (Nessie)
    back_transfer_id   text, back_deposit_id   text    -- borrower → lender on payday (Nessie)
);
CREATE INDEX IF NOT EXISTS bridges_borrower ON bridges (borrower_slug, status);
CREATE INDEX IF NOT EXISTS bridges_lender ON bridges (lender_slug, status);

CREATE TABLE IF NOT EXISTS safety_events (
    id            bigserial PRIMARY KEY,
    at            timestamptz NOT NULL DEFAULT now(),
    persona_slug  text NOT NULL,              -- whose feed this appears in
    kind          text NOT NULL,
    message       text NOT NULL,
    bridge_id     text
);
CREATE INDEX IF NOT EXISTS safety_events_persona ON safety_events (persona_slug, at DESC);
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


# The forecast's track record, from forecasts it really showed (not a replay). One row per persona,
# per day the forecast was made (`made_on`, the time column), per day it was for. Each row is made
# once and never rewritten (see db/forecast_repo.py); once its target day has passed, the background
# pass fills in what really happened (`actual`) and the score (`abs_error`, `in_band`).
FORECAST_SNAPSHOTS = """
CREATE TABLE IF NOT EXISTS forecast_snapshots (
    persona_slug    text NOT NULL,
    made_on         date NOT NULL,
    target_date     date NOT NULL,
    lead_days       smallint NOT NULL CHECK (lead_days >= 1),  -- 1 = the end of the day it was made
    balance         numeric(12, 2) NOT NULL,                   -- predicted end-of-day checking balance
    balance_low     numeric(12, 2),                            -- p5 / p90 band, when the engine had one
    balance_high    numeric(12, 2),
    engine_version  text NOT NULL,
    readiness       text,                                      -- calibrating | learning | confident
    created_at      timestamptz NOT NULL DEFAULT now(),
    actual          numeric(12, 2),                            -- real end-of-day balance, once known
    abs_error       numeric(12, 2),
    in_band         boolean,                                   -- NULL when there was no band
    scored_at       timestamptz,
    PRIMARY KEY (persona_slug, made_on, target_date)           -- includes the time column, as hypertables need
);
SELECT create_hypertable('forecast_snapshots', by_range('made_on', INTERVAL '30 days'), if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS forecast_snapshots_target ON forecast_snapshots (persona_slug, target_date);
"""

# Why a continuous aggregate over the snapshots alone, with no join: a continuous aggregate can join a
# hypertable to a plain table, but it only notices changes to the hypertable, so a join to a table of
# actual balances would keep stale scores once a bucket was materialized. Instead the background pass
# writes the actual balance and the score onto the snapshot row itself — an UPDATE on the hypertable,
# which TimescaleDB does track — and the aggregate only adds up sums and counts. Sums, not averages,
# so any number of days can be combined exactly (forecast/snapshots.combine).
FORECAST_ACCURACY = f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS forecast_accuracy_daily
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT time_bucket(INTERVAL '1 day', made_on)    AS day,
       persona_slug,
       lead_days,
       count(*)                                  AS days_scored,
       sum(abs_error)                            AS abs_error_sum,
       count(in_band)                            AS banded,
       count(*) FILTER (WHERE in_band)           AS in_band
FROM forecast_snapshots
WHERE actual IS NOT NULL AND lead_days IN ({", ".join(str(n) for n in TRACKED_LEADS)})
GROUP BY day, persona_slug, lead_days
WITH NO DATA;

-- refreshes the last 120 days every hour: scores keep landing for weeks after a forecast is made
-- (a 30-day-ahead row is scored a month later), and real-time aggregation covers the newest rows
SELECT add_continuous_aggregate_policy('forecast_accuracy_daily',
    start_offset => INTERVAL '120 days', end_offset => INTERVAL '1 day',
    schedule_interval => INTERVAL '1 hour', if_not_exists => TRUE);

-- a year of raw snapshots is plenty; the aggregate keeps its rows after the raw chunks are dropped,
-- because its refresh window (120 days) never reaches back that far
SELECT add_retention_policy('forecast_snapshots', INTERVAL '400 days', if_not_exists => TRUE);
"""

# compressed after 90 days: by then every row has been scored (30 days ahead, rescored for 35 days)
SNAPSHOT_COMPRESSION = """
ALTER TABLE forecast_snapshots SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'persona_slug',
    timescaledb.compress_orderby = 'made_on DESC, target_date'
);
SELECT add_compression_policy('forecast_snapshots', INTERVAL '90 days', if_not_exists => TRUE);
"""


def _compress_once(conn: psycopg.Connection, table: str, ddl: str) -> None:
    """Turn on compression for `table` unless it already is: re-running ALTER TABLE ... SET
    (timescaledb.compress) on a hypertable with compressed chunks would fail."""
    enabled = conn.execute(
        "SELECT compression_enabled FROM timescaledb_information.hypertables WHERE hypertable_name = %s", (table,)
    ).fetchone()
    if enabled and not list(enabled.values())[0]:
        conn.execute(ddl)


def apply(conn: psycopg.Connection) -> None:
    """Create or update every table, the hypertables, the continuous aggregates and their policies."""
    conn.autocommit = True  # continuous-aggregate DDL cannot run inside a transaction block
    try:
        conn.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
        for block in (TABLES, P2P, SAFETY_NET, MONEY_PREFS, HYPERTABLE, DAILY_SPEND, POLICIES):
            conn.execute(block)
        _compress_once(conn, "transactions", COMPRESSION)
        try:  # the track record is informational: if its DDL fails, everything else still works
            conn.execute(FORECAST_SNAPSHOTS)
            conn.execute(FORECAST_ACCURACY)
            _compress_once(conn, "forecast_snapshots", SNAPSHOT_COMPRESSION)
        except psycopg.Error:
            log.exception("could not apply the forecast-history schema; report cards will replay")
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


def refresh_forecast_accuracy(conn: psycopg.Connection) -> None:
    """Materialize the report-card aggregate now, so new scores count straight away (the policy also
    refreshes it hourly). Rows that were already materialized only change through a refresh."""
    conn.autocommit = True
    try:
        conn.execute("CALL refresh_continuous_aggregate('forecast_accuracy_daily', NULL, NULL)")
    finally:
        conn.autocommit = False

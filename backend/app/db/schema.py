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


def apply(conn: psycopg.Connection) -> None:
    """Create or update every table, the hypertable, the continuous aggregate and its policies."""
    conn.autocommit = True  # continuous-aggregate DDL cannot run inside a transaction block
    try:
        conn.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
        for block in (TABLES, P2P, SAFETY_NET, HYPERTABLE, DAILY_SPEND, POLICIES):
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

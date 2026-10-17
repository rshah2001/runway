// Mirrors backend/app/schemas.py — the API contract.
// Change both files in the same PR, or web/iOS/Android will drift from the backend.

export type Account = {
  id: string;
  nickname: string;
  type: 'Checking' | 'Savings' | 'Credit Card';
  balance: number;
};

export type Me = {
  customer_id: string;
  first_name: string;
  accounts: Account[];
  safe_floor: number; // what this person keeps in checking (default 300)
};

export type ForecastPoint = {
  date: string; // 'YYYY-MM-DD'
  balance: number; // expected end-of-day balance
  balance_low?: number | null; // p5: the cautious end, if everyday spending runs high
  balance_high?: number | null; // p90
};

export type ForecastEvent = {
  date: string;
  amount: number; // negative = money out
  label: string;
  kind: 'paycheck' | 'bill' | 'subscription' | 'card_payment' | 'spending' | 'transfer' | 'other';
};

export type LeftOut = { date: string; amount: number; label: string }; // a one-off kept out of the rate

export type Readiness = {
  status: 'calibrating' | 'learning' | 'confident';
  days_of_history: number;
  paychecks_seen: number;
  paycheck_found: boolean; // the forecast has a learned payday in it
  spend_days: number; // days the everyday spending rate was learned from
  progress: number; // 0–1 toward "confident"
  reasons: string[]; // plain English, safe to show as-is
  rolling_error?: number | null; // $: how far off its week-ahead forecasts were, on average, lately
  rolling_error_days?: number; // how many recent days that average covers
  // where that average comes from: 'saved' = forecasts the app really showed, kept in Tiger Data and
  // checked once the day passed; 'replay' = the engine re-run on past days (until enough are saved)
  rolling_error_source?: 'saved' | 'replay' | null;
  band_coverage?: number | null; // 0–1: share of checked days the real balance was inside the range
  left_out?: LeftOut[]; // one-offs kept out of the spending rate
};

export type Forecast = {
  points: ForecastPoint[];
  low: ForecastPoint;
  safe_floor: number;
  events: ForecastEvent[];
  readiness?: Readiness | null;
  cautious_low?: ForecastPoint | null; // the day with the lowest p5 balance: what to plan around
};

export type Recurring = {
  merchant: string;
  amount: number;
  interval_days: number;
  next_date: string;
};

export type PendingAction = {
  id: string;
  kind: 'transfer' | 'reschedule_bill' | 'p2p_request'; // p2p_request: ask a contact to pay you back
  description: string;
  amount: number | null;
  status: 'awaiting_approval' | 'approved' | 'declined' | 'executed' | 'failed'; // failed = check with the bank, never retry
};

export type ChatResponse = {
  reply: string;
  tool_calls: string[];
  pending_action: PendingAction | null;
};

export type Persona = { slug: string; first_name: string; age: number; story: string };

export type CategorySpend = { category: string; spent: number; purchases: number };

export type DailySpend = { date: string; spent: number };

export type SpendingTransaction = {
  date: string;
  merchant: string;
  category: string;
  amount: number; // positive = money spent
  account: string;
};

export type Spending = {
  month: string; // 'YYYY-MM'
  total: number;
  categories: CategorySpend[]; // biggest first
  daily: DailySpend[]; // from the Tiger Data continuous aggregate in live mode
  transactions: SpendingTransaction[]; // newest first
};

// ---------- peer-to-peer ----------
export type Contact = { id: string; name: string; relation: string; owes_you: number };

export type P2PPayment = {
  id: string;
  date: string;
  direction: 'in' | 'out'; // in = the contact paid you
  contact_id: string;
  contact: string;
  amount: number;
  memo: string;
};

export type P2PRequest = {
  id: string;
  contact_id: string;
  contact: string;
  amount: number; // the contact owes you this
  memo: string;
  status: 'open' | 'settling' | 'paid' | 'declined' | 'failed';
  created: string;
};

export type P2PSummary = {
  contacts: Contact[];
  payments: P2PPayment[]; // newest first
  requests: P2PRequest[]; // open first
};

// ---------- family safety net ----------
export type SafetyLimit = {
  lender: string;
  lender_name: string;
  borrower: string;
  borrower_name: string;
  limit: number; // moved without asking, if it comes back by the borrower's next payday
  outstanding: number; // lent and not back yet
  remaining: number;
  enabled: boolean;
};

export type BridgeStatus =
  | 'pending_approval' // over the limit: waiting for the lender (Auth0 push or in-app)
  | 'declined'
  | 'funding'
  | 'active' // money is with the borrower; comes back on due_date
  | 'repaying'
  | 'repaid' // show the lender: "you got it back" (repaid_on)
  | 'repay_failed' // late — no new bridges until it's back
  | 'failed';

export type Bridge = {
  id: string;
  borrower: string;
  borrower_name: string;
  lender: string;
  lender_name: string;
  amount: number;
  reason: string; // plain-English explanation from the engine
  status: BridgeStatus;
  mode: 'auto' | 'approval'; // auto = under the lender's limit, nobody had to ask
  approval_channel: 'auth0_push' | 'in_app' | null;
  shortfall_date: string; // the day the borrower would have dipped
  due_date: string; // repaid automatically on this payday
  created: string;
  funded_on: string | null;
  repaid_on: string | null;
};

export type SafetyEvent = { at: string; kind: string; message: string; bridge_id: string | null };

/** GET /demo/status: the demo reset, and how long automatic bridges are paused for the live demo. */
export type DemoStatus = {
  state: 'idle' | 'running' | 'done' | 'failed';
  started: string | null;
  finished: string | null;
  error: string | null; // the kind of failure only
  hold_until: string | null;
};

export type SafetyNetSummary = {
  persona: string;
  next_payday: string | null;
  projected_low: { date: string; balance: number } | null; // lowest balance before next payday
  limits_i_set: SafetyLimit[]; // as a lender (editable)
  limits_for_me: SafetyLimit[]; // family covering me
  borrowed: Bridge[];
  lent: Bridge[]; // with due_date / repaid_on — when the money comes back
  approvals_waiting: Bridge[]; // over-limit bridges waiting for MY approval
  events: SafetyEvent[]; // newest first
};

export type SafetyDecision = {
  borrower: string;
  action: 'none' | 'auto_bridge' | 'needs_approval' | 'no_safe_helper' | 'no_payday' | 'already_covered';
  reason: string;
  amount: number;
  lender: string | null;
  shortfall_date: string | null;
  low_balance: number | null;
  due_date: string | null;
  executed: boolean; // false = dry run (real transfers off) or nothing to do
  bridge: Bridge | null;
};

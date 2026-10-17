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
  alerts_only?: boolean; // Today shows one calm line and speaks up only before a dip (older servers: absent)
  family_cover?: boolean;
  discreet_notifications?: boolean; // lock-screen previews carry no amounts or names // false: family limits never move money to this person
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

export type CategoryChange = { category: string; this: number; last: number; change: number }; // change < 0 = spending less

/** Against the previous month: the SAME days of it while this month is in progress. */
export type SpendingCompare = {
  previous_month: string; // 'YYYY-MM'
  through_day: number | null; // compared through this day of each month; null = whole months
  this_total: number;
  last_total: number;
  change: number; // negative = spending less than last month
  categories: CategoryChange[]; // biggest change first
};

export type Spending = {
  month: string; // 'YYYY-MM'
  total: number;
  categories: CategorySpend[]; // biggest first
  daily: DailySpend[]; // from the Tiger Data continuous aggregate in live mode
  transactions: SpendingTransaction[]; // newest first
  compare?: SpendingCompare | null; // vs the previous month
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
  | 'reconcile' // the bank left the outcome unclear: being confirmed, never sent twice
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
/** GET /alerts/key, PUT /me/push, POST /me/push/test. */
export type PushStatus = {
  key: string | null; // the server's public key for Web Push; null = alerts to phones are off
  sent: number; // browsers reached (test alerts)
};

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
  action: 'none' | 'auto_bridge' | 'needs_approval' | 'no_safe_helper' | 'no_payday' | 'already_covered' | 'family_off';
  reason: string;
  amount: number;
  lender: string | null;
  shortfall_date: string | null;
  low_balance: number | null;
  due_date: string | null;
  executed: boolean; // false = dry run (real transfers off) or nothing to do
  bridge: Bridge | null;
};

// ---------- Quiet Support Agreements (backend/app/schemas.py SupportAgreement / SupportSummary) ----------
export type AgreementState = 'active' | 'paused' | 'needs_supporter' | 'needs_recipient' | 'needs_both' | 'revoked';

/** One agreement as ONE side sees it. Never carries anyone's balance, income, spending or forecast. */
export type SupportAgreement = {
  supporter: string;
  supporter_name: string;
  recipient: string;
  recipient_name: string;
  my_side: 'supporter' | 'recipient';
  state: AgreementState;
  i_agreed: boolean;
  they_agreed: boolean;
  limit: number | null; // the supporter's own cap for this person
  outstanding: number; // supporter: owed to me · recipient: what I owe them
  version: number;
  mode?: 'auto' | 'approval'; // approval: the supporter wants to be asked every time
};

export type SupportSummary = {
  persona: string;
  supporting: SupportAgreement[]; // people I may help
  supporters: SupportAgreement[]; // people who may help me
  exposure_limit?: number; // the most I let Runway have out across everyone I support
  committed?: number; // what I have out (or promised) right now as a supporter
  max_owed?: number | null; // as a recipient: the most I'll owe at once (null = no cap)
  allow_multi?: boolean; // as a recipient: several people may cover one gap together
};

/** One support transfer or repayment from MY side, with a plain why (backend/app/activity.py). */
export type ActivityItem = {
  id: string;
  date: string;
  kind: 'received' | 'provided' | 'repaid_by_me' | 'repaid_to_me' | 'waiting' | 'pending_my_ok' | 'problem';
  title: string;
  amount: number;
  status: string;
  why: string;
  reference?: string | null; // the bank (Nessie) id of my side of the transfer
};

// ---------- Time Machine (backend/app/scenarios.py) ----------
export type ScenarioPoint = { date: string; balance: number };

/** One what-if on YOUR forecast. D is what Runway refuses to do (blocked); it names nobody. */
export type Scenario = {
  key: 'A' | 'B' | 'C' | 'D'; // A no help · B one supporter · C your circle · D unsafe help (blocked)
  label: string;
  help: number; // arrives today, goes back on payday
  low: ScenarioPoint; // the lowest point before payday
  covered: boolean; // the low stays at or above your cushion
  blocked: boolean;
  note: string;
  points: ScenarioPoint[]; // daily balance, for the chart
};

export type Scenarios = { floor: number; payday: string | null; need: number; scenarios: Scenario[] };

// ---------- Named circles (backend/app/circles.py) — membership only, never money ----------
export type CircleMember = { slug: string; name: string; state: 'invited' | 'active' };
export type CircleView = { id: string; name: string; made_by_me: boolean; my_state: 'invited' | 'active'; members: CircleMember[] };

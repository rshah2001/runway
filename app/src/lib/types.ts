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
};

export type ForecastPoint = { date: string; balance: number }; // date = 'YYYY-MM-DD'

export type ForecastEvent = {
  date: string;
  amount: number; // negative = money out
  label: string;
  kind: 'paycheck' | 'bill' | 'subscription' | 'card_payment' | 'spending' | 'transfer' | 'other';
};

export type Forecast = {
  points: ForecastPoint[];
  low: ForecastPoint;
  safe_floor: number;
  events: ForecastEvent[];
};

export type Recurring = {
  merchant: string;
  amount: number;
  interval_days: number;
  next_date: string;
};

export type PendingAction = {
  id: string;
  kind: 'transfer' | 'reschedule_bill';
  description: string;
  amount: number | null;
  status: 'awaiting_approval' | 'approved' | 'declined' | 'executed';
};

export type ChatResponse = {
  reply: string;
  tool_calls: string[];
  pending_action: PendingAction | null;
};

export type Persona = { slug: string; first_name: string; story: string };

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

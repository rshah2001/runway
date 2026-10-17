// Display formatting only — no money math happens here.

/** "$1,234.56", or "−$35" with `dp = 0`. Uses a true minus sign so columns line up. */
export function money(n: number, dp = 2): string {
  const s = Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: dp, maximumFractionDigits: dp });
  return `${n < 0 ? '−' : ''}$${s}`;
}

/** "+$780" / "−$35" — for amounts where direction matters. */
export function signed(n: number, dp = 2): string {
  return `${n >= 0 ? '+' : ''}${money(n, dp)}`;
}

/** Parses the API's 'YYYY-MM-DD' as a local date (never UTC, so the day doesn't shift). */
export function fromIso(s: string): Date {
  const [y, m, d] = s.split('-').map(Number);
  return new Date(y, m - 1, d);
}

/** "Oct 22" */
export const monthDay = (s: string) => fromIso(s).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
/** "Thu, Oct 22" */
export const weekdayDate = (s: string) =>
  fromIso(s).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
/** "Thu" */
export const weekday = (s: string) => fromIso(s).toLocaleDateString('en-US', { weekday: 'short' });

/** 'YYYY-MM' → "October" / "Oct" */
export function monthName(ym: string, style: 'long' | 'short' = 'long'): string {
  return new Date(Number(ym.slice(0, 4)), Number(ym.slice(5)) - 1, 1).toLocaleDateString('en-US', { month: style });
}

/** The last `n` months as 'YYYY-MM', oldest first, ending with the current month. */
export function recentMonths(n: number): string[] {
  const out: string[] = [];
  const d = new Date();
  d.setDate(1);
  for (let i = n - 1; i >= 0; i--) {
    const m = new Date(d.getFullYear(), d.getMonth() - i, 1);
    out.push(`${m.getFullYear()}-${String(m.getMonth() + 1).padStart(2, '0')}`);
  }
  return out;
}

/** The backend's feed messages and memos can start or end with an emoji; the screens use plain words only. */
export const plain = (message: string) => message.replace(/^\p{Extended_Pictographic}\uFE0F?\s*|\s*\p{Extended_Pictographic}\uFE0F?$/gu, '');

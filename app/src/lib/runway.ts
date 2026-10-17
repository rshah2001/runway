/**
 * Reading the forecast for the Today screen. Every balance comes from the backend's forecast engine;
 * these helpers only pick facts out of it (which day is first under the floor, how many dips).
 */
import type { Forecast, ForecastEvent } from './types';

/** Days until checking first falls under the safety floor; the horizon length if it never does. */
export function runwayDays(f: Forecast): number {
  const i = f.points.findIndex((p) => p.balance < f.safe_floor);
  return i === -1 ? f.points.length - 1 : i;
}

/** True when the whole horizon stays at or above the floor. */
export const isClear = (f: Forecast) => runwayDays(f) >= f.points.length - 1;

/** Separate stretches under the floor ("2 dips"). */
export function dipCount(f: Forecast): number {
  return f.points.filter((p, i) => p.balance < f.safe_floor && (i === 0 || f.points[i - 1].balance >= f.safe_floor)).length;
}

/** The contract's definition (docs/TEAM_PROMPTS.md): what's left above the floor on the tightest day. */
export const safeToSpend = (f: Forecast) => Math.max(0, Math.floor(f.low.balance - f.safe_floor));

/** Scheduled bills and pay in the next `days` days (estimated everyday spending left out). */
export function upcoming(f: Forecast, days = 14): ForecastEvent[] {
  const start = f.points[0]?.date ?? '';
  const end = f.points[Math.min(days, f.points.length - 1)]?.date ?? start;
  return f.events.filter((e) => e.date > start && e.date <= end && e.kind !== 'spending');
}

/**
 * TODO(engine): delete once GET /forecast includes executed transfers.
 * The mock engine (backend/app/forecast/engine.py) ignores money movement, so after an approved
 * savings → checking transfer the app lifts every point from today on by the transferred amount.
 * Display-only; it never feeds back into any decision.
 */
export function withApprovedTransfer(f: Forecast, amount: number): Forecast {
  if (!amount) return f;
  const points = f.points.map((p) => ({ ...p, balance: Math.round((p.balance + amount) * 100) / 100 }));
  const low = points.reduce((m, p) => (p.balance < m.balance ? p : m), points[0]);
  return { ...f, points, low };
}

/** Calendar days from the forecast's first day (today) to `date`. */
export function daysFromToday(f: Forecast, date: string): number {
  const [y0, m0, d0] = f.points[0].date.split('-').map(Number);
  const [y1, m1, d1] = date.split('-').map(Number);
  return Math.round((Date.UTC(y1, m1 - 1, d1) - Date.UTC(y0, m0 - 1, d0)) / 86_400_000);
}

/** The next paycheck in the forecast, if one lands inside the horizon. */
export const nextPaycheck = (f: Forecast): ForecastEvent | undefined =>
  f.events.find((e) => e.kind === 'paycheck' && e.date > f.points[0].date);

/** Days between paychecks, read off the forecast's own paycheck events (biweekly when only one is visible). */
export function payCycleDays(f: Forecast): number {
  const pays = f.events.filter((e) => e.kind === 'paycheck');
  return pays.length >= 2 ? daysFromToday(f, pays[1].date) - daysFromToday(f, pays[0].date) : 14;
}

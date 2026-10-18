/**
 * Tiny app-wide store for what the screens must share: an approval made in the chat has to reach Today
 * (so the chart updates and the plane takes off there). Plain module state + useSyncExternalStore —
 * no library needed for a handful of fields.
 */
import { useSyncExternalStore } from 'react';

import type { PendingAction } from './types';

type State = {
  /** Total of transfers approved this session (see withApprovedTransfer). */
  approvedAmount: number;
  /** Set by an approval; Today plays the takeoff once and clears it. */
  celebrate: boolean;
  /** The chat panel (opened from the floating button on every screen). */
  chatOpen: boolean;
  /** A money move waiting for the user's answer in the approval sheet (components/rw/approval-sheet.tsx). */
  approval: ApprovalRequest | null;
  /** Family notes the user closed on Today (by event time), so they stay closed while the app is open. */
  dismissed: string[];
  /**
   * Bumped whenever money moves or a money setting changes (a payment, a repayment, an approval, a
   * limit, what you keep, a demo reset). Every screen keys its loads on it, so they all re-fetch.
   */
  dataVersion: number;
  /** Alerts-only is on but the user asked to see the numbers this once (Today's "Show my numbers"). */
  peek: boolean;
};

/** What the approval sheet shows: the agent's proposal plus the facts Today read off the forecast. */
export type ApprovalRequest = {
  action: PendingAction;
  title: string;
  lead: string;
  facts: [label: string, value: string][];
};

let state: State = { approvedAmount: 0, celebrate: false, chatOpen: false, approval: null, dismissed: [], dataVersion: 0, peek: false };
const listeners = new Set<() => void>();

/** Money moved (or a money setting changed): every screen re-fetches what it shows. */
/**
 * Keep every open account current: another person paying you, approving, or the background safety-net pass
 * all change what you should see. Refreshes every `everyMs` (30 s) while the page is visible, and at once when you
 * come back to it. Each screen re-fetches in place (useLoad keeps the old data until the new arrives).
 * Returns a stop function.
 */
export function startAutoRefresh(everyMs = 30000): () => void {
  const visible = () => typeof document === 'undefined' || document.visibilityState !== 'hidden';
  const timer = setInterval(() => visible() && moneyMoved(), everyMs);
  const onShow = () => visible() && moneyMoved();
  if (typeof document !== 'undefined') document.addEventListener('visibilitychange', onShow);
  return () => {
    clearInterval(timer);
    if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', onShow);
  };
}

export function moneyMoved() {
  setStore({ dataVersion: state.dataVersion + 1 });
}

export function setStore(patch: Partial<State>) {
  state = { ...state, ...patch };
  listeners.forEach((l) => l());
}

export function useStore(): State {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => state,
    () => state,
  );
}

/** The current state outside React (event handlers). */
export const getStore = () => state;

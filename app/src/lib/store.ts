/**
 * Tiny app-wide store for what the screens must share: an approval made in the chat has to reach Today
 * (so the chart updates and the plane takes off there). Plain module state + useSyncExternalStore —
 * no library needed for two fields.
 */
import { useSyncExternalStore } from 'react';

type State = {
  /** Total of transfers approved this session (see withApprovedTransfer). */
  approvedAmount: number;
  /** Set by an approval; Today plays the takeoff once and clears it. */
  celebrate: boolean;
  /** The chat panel (opened from the floating button on every screen). */
  chatOpen: boolean;
};

let state: State = { approvedAmount: 0, celebrate: false, chatOpen: false };
const listeners = new Set<() => void>();

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

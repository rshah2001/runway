/**
 * Who is using the app: signed in with Auth0, or not yet.
 * Plain module state + useSyncExternalStore (like lib/store.ts). No imports from api.ts, so api.ts
 * can read `currentPersona()` for its defaults without an import cycle.
 */
import { useSyncExternalStore } from 'react';

export type Mode = 'checking' | 'signed-out' | 'signed-in';
export type Session = { mode: Mode; persona: string; name: string | null };

let session: Session = { mode: 'checking', persona: 'maya', name: null };
const listeners = new Set<() => void>();

export function setSession(patch: Partial<Session>) {
  session = { ...session, ...patch };
  listeners.forEach((l) => l());
}

export function useSession(): Session {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => session,
    () => session,
  );
}

/** The current session outside React (event handlers, api.ts). */
export const getSession = () => session;

/** The persona every API call defaults to. Signed in, the server ignores it and uses the account's own. */
export const currentPersona = () => session.persona;


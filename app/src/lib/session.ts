/**
 * Who is using the app: signed in with Auth0, looking around as a demo customer, or neither yet.
 * Plain module state + useSyncExternalStore (like lib/store.ts). No imports from api.ts, so api.ts
 * can read `currentPersona()` for its defaults without an import cycle.
 */
import { useSyncExternalStore } from 'react';
import { Platform } from 'react-native';

export type Mode = 'checking' | 'signed-out' | 'guest' | 'signed-in';
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

// A guest choice survives a page refresh on the website (per tab, like the Auth0 session), never longer.
const GUEST_KEY = 'runway.guest';

export function rememberGuest(slug: string | null) {
  if (Platform.OS !== 'web') return;
  try {
    if (slug) sessionStorage.setItem(GUEST_KEY, slug);
    else sessionStorage.removeItem(GUEST_KEY);
  } catch {
    // private mode or storage blocked: the choice just won't survive a refresh
  }
}

export function restoreGuest(): string | null {
  if (Platform.OS !== 'web') return null;
  try {
    return sessionStorage.getItem(GUEST_KEY);
  } catch {
    return null;
  }
}

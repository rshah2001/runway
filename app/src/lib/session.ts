/**
 * Who is using the app: signed in with Auth0, looking around as a demo customer, or neither yet.
 * Plain module state + useSyncExternalStore (like lib/store.ts). No imports from api.ts, so api.ts
 * can read `currentPersona()` for its defaults without an import cycle.
 */
import { useSyncExternalStore } from 'react';
import { Platform } from 'react-native';

// guest: browsing a demo customer without an account. Read-only: the server refuses every change and
// every money move from a caller with no token (main.authorize_money / _own_settings).
export type Mode = 'checking' | 'signed-out' | 'guest' | 'signed-in';
export type Session = {
  mode: Mode;
  persona: string;
  name: string | null;
  /** a message for the login screen, e.g. why the last sign-in didn't finish */
  notice?: string | null;
};

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
    const slug = sessionStorage.getItem(GUEST_KEY);
    return slug && /^[a-z]{1,32}$/.test(slug) ? slug : null; // same shape the API accepts
  } catch {
    return null;
  }
}

/**
 * Getting in and out: Auth0 sign-in, looking around as a demo customer, signing out.
 * Each step that ends on the login screen returns its result first, so the screen can play the
 * takeoff before the app replaces it (`enter…` commits the session).
 */
import { api } from './api';
import { isSignedIn, login, logout } from './auth';
import { getSession, rememberGuest, restoreGuest, setSession } from './session';

export type Profile = { persona: string; name: string };

const titleCase = (slug: string) => slug.charAt(0).toUpperCase() + slug.slice(1);

/** Whose data the signed-in account sees — the server decides, from the Auth0 token. */
async function signedInProfile(): Promise<Profile> {
  const me = await api.me();
  return { persona: me.first_name.toLowerCase(), name: me.first_name };
}

/** On launch: resume an Auth0 session, else a demo choice from this tab, else the login screen. */
export async function bootSession(): Promise<void> {
  try {
    if (await isSignedIn()) {
      const p = await signedInProfile();
      setSession({ mode: 'signed-in', ...p });
      return;
    }
  } catch {
    // an expired or unlinked session falls through to the login screen
  }
  const guest = restoreGuest();
  setSession(guest ? { mode: 'guest', persona: guest, name: titleCase(guest) } : { mode: 'signed-out' });
}

export class NotLinked extends Error {}

/** Opens Auth0. Resolves to the profile, or null if the person closed the sign-in window. */
export async function signIn(): Promise<Profile | null> {
  if (!(await login())) return null;
  try {
    return await signedInProfile();
  } catch (e) {
    // 403 from the API: signed in fine, but the account isn't linked to a Runway profile yet
    if (e instanceof Error && e.message.includes('403')) {
      await logout();
      throw new NotLinked('This account isn’t linked to a Runway profile yet.');
    }
    throw e;
  }
}

export function enterSignedIn(p: Profile) {
  rememberGuest(null);
  setSession({ mode: 'signed-in', ...p });
}

export function enterAsGuest(p: Profile) {
  rememberGuest(p.persona);
  setSession({ mode: 'guest', ...p });
}

/** Back to the login screen. Signed in, this also ends the Auth0 session. */
export async function leave(): Promise<void> {
  if (getSession().mode === 'signed-in') await logout();
  rememberGuest(null);
  setSession({ mode: 'signed-out', persona: 'maya', name: null });
}

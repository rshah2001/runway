/**
 * Getting in and out: Auth0 sign-in and sign-out. There is no anonymous way in.
 * Each step that ends on the login screen returns its result first, so the screen can play the
 * takeoff before the app replaces it (`enter…` commits the session).
 */
import { api } from './api';
import { isSignedIn, login, logout } from './auth';
import { setSession } from './session';

export type Profile = { persona: string; name: string };

/** Whose data the signed-in account sees — the server decides, from the Auth0 token. */
async function signedInProfile(): Promise<Profile> {
  const me = await api.me();
  return { persona: me.first_name.toLowerCase(), name: me.first_name };
}

/** On launch: resume an Auth0 session, else the login screen. */
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
  setSession({ mode: 'signed-out' });
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
  setSession({ mode: 'signed-in', ...p });
}

/** Ends the Auth0 session and returns to the login screen. */
export async function leave(): Promise<void> {
  await logout();
  setSession({ mode: 'signed-out', persona: 'maya', name: null });
}

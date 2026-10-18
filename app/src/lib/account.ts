/**
 * Getting in and out: Auth0 sign-in and sign-out. There is no anonymous way in.
 * Each step that ends on the login screen returns its result first, so the screen can play the
 * takeoff before the app replaces it (`enter…` commits the session).
 */
import { api } from './api';
import { router } from 'expo-router';
import { Platform } from 'react-native';

import { httpStatus } from '../hooks/use-load';
import { AFTER_KEY, completeWebSignIn, forgetSession, isSignedIn, login, logout } from './auth';
import { setSession } from './session';

export type Profile = { persona: string; name: string };

/** Whose data the signed-in account sees — the server decides, from the Auth0 token. */
async function signedInProfile(): Promise<Profile> {
  const me = await api.me();
  return { persona: me.first_name.toLowerCase(), name: me.first_name };
}

/** On launch: finish a sign-in Auth0 just returned from (web), resume a session, else the login screen. */
export async function bootSession(): Promise<void> {
  // back from Auth0: once handled, drop ?code=…&state=… from the address (via the router, which
  // would otherwise put its own copy of the URL back)
  if (Platform.OS === 'web' && typeof window !== 'undefined' && /[?&](code|error)=/.test(window.location.search)) {
    setTimeout(() => {
      try {
        const after = window.sessionStorage.getItem(AFTER_KEY);
        window.sessionStorage.removeItem(AFTER_KEY);
        router.replace((after && /^\/join\/[A-Za-z0-9_-]{20,40}$/.test(after) ? after : '/') as never);
      } catch {
        // router not mounted yet: the address keeps a used, one-time code — harmless
      }
    }, 0);
  }
  try {
    await completeWebSignIn();
  } catch (e) {
    setSession({ mode: 'signed-out', notice: `Sign-in didn’t finish: ${e instanceof Error ? e.message : 'please try again'}.` });
    return;
  }
  try {
    if (await isSignedIn()) {
      const p = await signedInProfile();
      setSession({ mode: 'signed-in', ...p });
      return;
    }
  } catch (e) {
    // an expired or unlinked session goes back to the login screen, saying why
    const code = httpStatus(e instanceof Error ? e.message : '');
    await forgetSession();
    setSession({
      mode: 'signed-out',
      notice: code === 403 ? 'This account isn’t linked to a Runway profile yet.' : `Sign-in didn’t finish${code ? ` (error ${code})` : ''}. Please try again.`,
    });
    return;
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

// Auth0 sign-in for web, iOS and Android — owner: Patil-Hemangi.
//
// Authorization-code flow with PKCE in the system browser (expo-auth-session, SDK 58): the app is a
// public client, so no client secret ever ships in it. The access token is for our API (`audience`)
// and is sent as `Authorization: Bearer …`; the backend verifies it (backend/app/auth).
//
// Configure in app/.env (these are public identifiers, not secrets):
//   EXPO_PUBLIC_AUTH0_DOMAIN=your-tenant.us.auth0.com
//   EXPO_PUBLIC_AUTH0_CLIENT_ID=…            (the Native application's client id)
//   EXPO_PUBLIC_AUTH0_AUDIENCE=https://…/api  (the API identifier)
// Native sign-in needs a development build: Expo Go can't complete OAuth redirects.
import * as AuthSession from 'expo-auth-session';
import { TokenTypeHint } from 'expo-auth-session';
import * as SecureStore from 'expo-secure-store';
import * as WebBrowser from 'expo-web-browser';
import { Platform } from 'react-native';

// Web signs in with a same-tab redirect (see `login`), not a popup: phone browsers block popups that
// aren't opened in the same instant as the tap, and a popup tab on a phone can't hand the result
// back. This call stays harmless — it only acts if a popup-based sign-in is somehow in flight.
WebBrowser.maybeCompleteAuthSession();

const DOMAIN = (process.env.EXPO_PUBLIC_AUTH0_DOMAIN ?? '').replace(/^https?:\/\//, '').replace(/\/$/, '');
const CLIENT_ID = process.env.EXPO_PUBLIC_AUTH0_CLIENT_ID ?? '';
const AUDIENCE = process.env.EXPO_PUBLIC_AUTH0_AUDIENCE ?? '';
const ISSUER = `https://${DOMAIN}`;
const SCOPES = ['openid', 'profile', 'email', 'offline_access']; // offline_access → a refresh token
const STORE_KEY = 'runway.auth';
const REFRESH_MARGIN_SECONDS = 60; // refresh a little early so a request never carries an expired token

export const isAuthConfigured = Boolean(DOMAIN && CLIENT_ID && AUDIENCE);

type Session = {
  accessToken: string;
  refreshToken?: string;
  idToken?: string;
  expiresIn?: number;
  issuedAt: number;
};

let session: Session | null = null;
let restored = false;
let discovery: AuthSession.DiscoveryDocument | null = null;

/**
 * Where Auth0 sends the user back; each value must be in the Auth0 app's Allowed Callback URLs.
 * Native: runway://auth (caught by the browser session). Web: the site root, e.g. http://localhost:8081,
 * where `completeWebSignIn` picks up the returning code.
 */
export function redirectUri(): string {
  return AuthSession.makeRedirectUri({ scheme: 'runway', path: Platform.OS === 'web' ? undefined : 'auth' });
}

// Web redirect sign-in: what we must remember across the trip to Auth0 (this tab only).
const PKCE_KEY = 'runway.pkce';

/**
 * Opens Auth0's sign-in page. Native: the system sign-in sheet; resolves true when signed in, false
 * if the user closed it. Web: goes to Auth0 in this tab (the promise never settles — the page
 * leaves), and `completeWebSignIn` finishes the job when Auth0 sends the user back.
 */
export async function login(): Promise<boolean> {
  requireConfig();
  const config = await getDiscovery();
  if (Platform.OS === 'web') {
    const request = new AuthSession.AuthRequest({
      clientId: CLIENT_ID,
      redirectUri: redirectUri(),
      scopes: SCOPES,
      usePKCE: true,
      extraParams: { audience: AUDIENCE },
    });
    const url = await request.makeAuthUrlAsync(config);
    // the PKCE verifier proves the returning code is ours; `state` ties the return to this request
    window.sessionStorage.setItem(PKCE_KEY, JSON.stringify({ state: request.state, verifier: request.codeVerifier }));
    window.location.assign(url);
    return new Promise<boolean>(() => {}); // the page is leaving for Auth0
  }
  const request = new AuthSession.AuthRequest({
    clientId: CLIENT_ID,
    redirectUri: redirectUri(),
    scopes: SCOPES,
    usePKCE: true,
    extraParams: { audience: AUDIENCE },
  });
  const result = await request.promptAsync(config);
  if (result.type !== 'success') {
    if (result.type === 'error') throw new Error(result.error?.message ?? 'Sign-in failed');
    return false; // cancelled or dismissed
  }
  const tokens = await AuthSession.exchangeCodeAsync(
    {
      clientId: CLIENT_ID,
      code: result.params.code,
      redirectUri: redirectUri(),
      extraParams: { code_verifier: request.codeVerifier ?? '' },
    },
    config,
  );
  await save(fromTokens(tokens));
  return true;
}

/** Our own words for the errors Auth0 can send back — its error_description is never shown, since
 * anyone can put text in a link's address. */
const SIGN_IN_ERRORS: Record<string, string> = {
  access_denied: 'You cancelled the sign-in, or this account isn’t allowed in',
  login_required: 'Please sign in again',
  consent_required: 'Please sign in again',
  interaction_required: 'Please sign in again',
  unauthorized: 'This account isn’t allowed to use Runway',
};

/**
 * Web only: finishes a redirect sign-in when Auth0 has just sent the user back (`?code=…&state=…`).
 * Resolves true when a session was saved, false when there was nothing to finish (including any
 * return this tab didn't start — a forged or replayed link). Throws one of our fixed messages if
 * Auth0 sent back an error for our own request. Always removes the code from the address bar.
 */
export async function completeWebSignIn(): Promise<boolean> {
  if (Platform.OS !== 'web' || typeof window === 'undefined') return false;
  const params = new URLSearchParams(window.location.search);
  const code = params.get('code'), state = params.get('state'), error = params.get('error');
  if (!code && !error) return false;
  const saved = window.sessionStorage.getItem(PKCE_KEY);
  window.sessionStorage.removeItem(PKCE_KEY);
  window.history.replaceState(null, '', window.location.pathname); // never leave the code in the URL
  const pkce = saved ? (JSON.parse(saved) as { state?: string; verifier?: string }) : null;
  // a code or an error only counts if it answers the request this tab sent (matching state)
  if (!pkce?.verifier || !state || pkce.state !== state) return false;
  if (error) throw new Error(SIGN_IN_ERRORS[error] ?? 'Auth0 couldn’t sign you in');
  const tokens = await AuthSession.exchangeCodeAsync(
    { clientId: CLIENT_ID, code: code!, redirectUri: redirectUri(), extraParams: { code_verifier: pkce.verifier } },
    await getDiscovery(),
  );
  await save(fromTokens(tokens));
  return true;
}

/** A valid access token for the API, refreshed if it's about to expire; null when signed out. */
export async function getAccessToken(): Promise<string | null> {
  const current = await restore();
  if (!current) return null;
  if (AuthSession.TokenResponse.isTokenFresh(current, REFRESH_MARGIN_SECONDS)) return current.accessToken;
  if (!current.refreshToken || !isAuthConfigured) {
    await clear();
    return null;
  }
  try {
    const tokens = await AuthSession.refreshAsync(
      { clientId: CLIENT_ID, refreshToken: current.refreshToken },
      await getDiscovery(),
    );
    // Auth0 rotates refresh tokens; keep the old one only if a new one wasn't issued
    await save({ ...fromTokens(tokens), refreshToken: tokens.refreshToken ?? current.refreshToken });
    return session?.accessToken ?? null;
  } catch {
    await clear(); // refresh token expired or revoked: the user signs in again
    return null;
  }
}

/** Headers for an API request: `{ Authorization: 'Bearer …' }` when signed in, `{}` otherwise. */
export async function authHeader(): Promise<Record<string, string>> {
  const token = await getAccessToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** Signs out: revokes the refresh token, forgets the session, and ends the Auth0 browser session. */
export async function logout(): Promise<void> {
  const current = await restore();
  await clear();
  if (!isAuthConfigured) return;
  if (current?.refreshToken) {
    try {
      await AuthSession.revokeAsync(
        { clientId: CLIENT_ID, token: current.refreshToken, tokenTypeHint: TokenTypeHint.RefreshToken },
        await getDiscovery(),
      );
    } catch {
      // best effort: the local session is already gone, and Auth0 expires the token on its own
    }
  }
  const returnTo = redirectUri();
  const url = `${ISSUER}/v2/logout?client_id=${encodeURIComponent(CLIENT_ID)}&returnTo=${encodeURIComponent(returnTo)}`;
  if (Platform.OS === 'web') {
    window.location.assign(url); // same tab, like sign-in; Auth0 sends the user back to the site
    return;
  }
  await WebBrowser.openAuthSessionAsync(url, returnTo); // otherwise the next login skips the password
}

/** Forgets the session on this device only (no trip to Auth0) — e.g. a sign-in that isn't linked. */
export async function forgetSession(): Promise<void> {
  await clear();
}

/** Whether a session is stored (it may still need a refresh). */
export async function isSignedIn(): Promise<boolean> {
  return (await restore()) !== null;
}

// ---------- internals ----------

function requireConfig(): void {
  if (!isAuthConfigured) {
    throw new Error(
      'Auth0 is not configured: set EXPO_PUBLIC_AUTH0_DOMAIN, EXPO_PUBLIC_AUTH0_CLIENT_ID and EXPO_PUBLIC_AUTH0_AUDIENCE',
    );
  }
}

async function getDiscovery(): Promise<AuthSession.DiscoveryDocument> {
  discovery ??= await AuthSession.fetchDiscoveryAsync(ISSUER);
  return discovery;
}

function fromTokens(tokens: AuthSession.TokenResponse): Session {
  return {
    accessToken: tokens.accessToken,
    refreshToken: tokens.refreshToken,
    idToken: tokens.idToken,
    expiresIn: tokens.expiresIn,
    issuedAt: tokens.issuedAt ?? Math.floor(Date.now() / 1000),
  };
}

// Native: the device keychain/keystore. Web: this tab only (sessionStorage) — never localStorage,
// where a long-lived refresh token would outlive the tab and be readable by any script on the page.
async function readStored(): Promise<string | null> {
  if (Platform.OS === 'web') return typeof window === 'undefined' ? null : window.sessionStorage.getItem(STORE_KEY);
  return SecureStore.getItemAsync(STORE_KEY);
}

async function writeStored(value: string | null): Promise<void> {
  if (Platform.OS === 'web') {
    if (typeof window === 'undefined') return;
    if (value === null) window.sessionStorage.removeItem(STORE_KEY);
    else window.sessionStorage.setItem(STORE_KEY, value);
    return;
  }
  if (value === null) await SecureStore.deleteItemAsync(STORE_KEY);
  else await SecureStore.setItemAsync(STORE_KEY, value);
}

async function restore(): Promise<Session | null> {
  if (!restored) {
    restored = true;
    try {
      const raw = await readStored();
      session = raw ? (JSON.parse(raw) as Session) : null;
    } catch {
      session = null; // unreadable storage: treat as signed out
    }
  }
  return session;
}

async function save(next: Session): Promise<void> {
  session = next;
  restored = true;
  await writeStored(JSON.stringify(next));
}

async function clear(): Promise<void> {
  session = null;
  restored = true;
  await writeStored(null);
}

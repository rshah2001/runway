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

// On web, Auth0 redirects back into a popup; this closes it and hands the result to the opener.
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

/** Where Auth0 sends the user back. Add the value for each platform to the Auth0 app's callback URLs. */
export function redirectUri(): string {
  return AuthSession.makeRedirectUri({ scheme: 'runway', path: 'auth' });
}

/** Opens Auth0's sign-in page. Resolves true when signed in, false if the user closed it. */
export async function login(): Promise<boolean> {
  requireConfig();
  const config = await getDiscovery();
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
  await WebBrowser.openAuthSessionAsync(url, returnTo); // otherwise the next login skips the password
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

import type {
  ActivityItem,
  PeopleSummary,
  Bridge,
  CircleView,
  ChatResponse,
  DemoStatus,
  Forecast,
  Me,
  P2PPayment,
  P2PRequest,
  P2PSummary,
  PendingAction,
  Persona,
  PushStatus,
  Recurring,
  SafetyDecision,
  SafetyLimit,
  SafetyNetSummary,
  Scenarios,
  Spending,
  SupportSummary,
} from './types';
import { authHeader } from './auth';
import { currentPersona } from './session';

// Set EXPO_PUBLIC_API_URL in app/.env. On a physical phone use your laptop's LAN IP
// (e.g. http://192.168.1.20:8000); the Android emulator reaches the laptop at http://10.0.2.2:8000.
const BASE_URL = process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:8000';

// Signed in: every request carries the Auth0 access token, and the server answers with YOUR data
// whatever persona a call names. Signed out (or sign-in not configured): no token, demo personas.
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(await authHeader()), ...init?.headers },
  });
  if (!res.ok) throw new Error(`${init?.method ?? 'GET'} ${path} failed: ${res.status}`);
  return res.json() as Promise<T>;
}

export const api = {
  personas: () => request<Persona[]>('/personas'),
  // what you keep in checking: every "am I okay?" is measured against it (only for yourself)
  setSafeFloor: (amount: number, persona = currentPersona()) =>
    request<Me>('/me/safe-floor', { method: 'PUT', body: JSON.stringify({ persona, amount }) }),
  // alerts-only and family cover: on/off, only for yourself; a field left out stays as it is
  setPreferences: (prefs: { alerts_only?: boolean; family_cover?: boolean; discreet_notifications?: boolean }, persona = currentPersona()) =>
    request<Me>('/me/preferences', { method: 'PUT', body: JSON.stringify({ persona, ...prefs }) }),
  me: (persona = currentPersona()) => request<Me>(`/me?persona=${persona}`),
  // heads-up alerts to this phone (lib/push.ts): the server's public key, this browser's subscription, a test
  alertsKey: () => request<PushStatus>('/alerts/key'),
  pushSubscribe: (sub: { endpoint: string; p256dh: string; auth: string }, persona = currentPersona()) =>
    request<PushStatus>('/me/push', { method: 'PUT', body: JSON.stringify({ persona, ...sub }) }),
  pushTest: (persona = currentPersona()) => request<PushStatus>(`/me/push/test?persona=${persona}`, { method: 'POST' }),
  forecast: (days = 30, persona = currentPersona()) => request<Forecast>(`/forecast?days=${days}&persona=${persona}`),
  simulate: (amount: number, date: string, label = 'Purchase', persona = currentPersona()) =>
    request<Forecast>(`/simulate?persona=${persona}`, { method: 'POST', body: JSON.stringify({ amount, date, label }) }),
  recurring: (persona = currentPersona()) => request<Recurring[]>(`/recurring?persona=${persona}`),
  // month = 'YYYY-MM' (defaults to the current month on the server)
  spending: (month?: string, persona = currentPersona()) =>
    request<Spending>(`/spending?persona=${persona}${month ? `&month=${month}` : ''}`),
  // peer-to-peer — amount in dollars (max $1,000 per payment), memo 1–80 chars
  p2p: (persona = currentPersona()) => request<P2PSummary>(`/p2p?persona=${persona}`),
  // one client_key per tap: if the request is retried, the server returns the first payment instead of paying twice
  p2pSend: (contactId: string, amount: number, memo: string, persona = currentPersona(), clientKey = tapKey()) =>
    request<P2PPayment>('/p2p/send', {
      method: 'POST',
      body: JSON.stringify({ persona, contact_id: contactId, amount, memo, client_key: clientKey }),
    }),
  p2pRequest: (contactId: string, amount: number, memo: string, persona = currentPersona()) =>
    request<P2PRequest>('/p2p/requests', { method: 'POST', body: JSON.stringify({ persona, contact_id: contactId, amount, memo }) }),
  p2pSettle: (requestId: string) => request<P2PRequest>(`/p2p/requests/${requestId}/settle`, { method: 'POST' }),
  // family safety net
  safetyNet: (persona = currentPersona()) => request<SafetyNetSummary>(`/safety-net?persona=${persona}`),
  // Quiet Support Agreements: each person says yes (or stops) for their own side only
  support: (persona = currentPersona()) => request<SupportSummary>(`/support?persona=${persona}`),
  supportConsent: (supporter: string, recipient: string, persona = currentPersona()) =>
    request<SupportSummary>('/support/consent', { method: 'POST', body: JSON.stringify({ persona, supporter, recipient }) }),
  supportMode: (recipient: string, mode: 'auto' | 'approval', persona = currentPersona()) =>
    request<SupportSummary>('/support/mode', { method: 'PUT', body: JSON.stringify({ persona, recipient, mode }) }),
  supportReceiving: (maxOwed: number | null, allowMulti: boolean, persona = currentPersona()) =>
    request<SupportSummary>('/support/receiving', { method: 'PUT', body: JSON.stringify({ persona, max_owed: maxOwed, allow_multi: allowMulti }) }),
  supportExposure: (limit: number, persona = currentPersona()) =>
    request<SupportSummary>('/support/exposure', { method: 'PUT', body: JSON.stringify({ persona, limit }) }),
  activity: (persona = currentPersona()) => request<ActivityItem[]>(`/activity?persona=${persona}`),
  // send / request between people in my circles — any time, for anything
  people: (persona = currentPersona()) => request<PeopleSummary>(`/people?persona=${persona}`),
  sendTo: (to: string, amount: number, memo: string, persona = currentPersona(), clientKey = tapKey()) =>
    request<PeopleSummary>('/people/send', { method: 'POST', body: JSON.stringify({ persona, to, amount, memo, client_key: clientKey }) }),
  askFrom: (to: string, amount: number, memo: string, persona = currentPersona()) =>
    request<PeopleSummary>('/people/request', { method: 'POST', body: JSON.stringify({ persona, to, amount, memo }) }),
  answerAsk: (id: string, action: 'pay' | 'decline', persona = currentPersona()) =>
    request<PeopleSummary>(`/people/requests/${id}/${action}`, { method: 'POST', body: JSON.stringify({ persona }) }),
  // named circles: membership only — joining one never grants access to anyone's money
  circles: (persona = currentPersona()) => request<CircleView[]>(`/circles?persona=${persona}`),
  createCircle: (name: string, persona = currentPersona()) =>
    request<CircleView[]>('/circles', { method: 'POST', body: JSON.stringify({ persona, name }) }),
  circleAction: (id: string, action: 'invite' | 'remove' | 'accept' | 'decline' | 'leave', slug?: string, persona = currentPersona()) =>
    request<CircleView[]>(`/circles/${id}/${action}`, { method: 'POST', body: JSON.stringify({ persona, slug }) }),
  // Time Machine: your own forecast with no help / one supporter / your circle / unsafe help (blocked)
  scenarios: (persona = currentPersona()) => request<Scenarios>(`/forecast/scenarios?persona=${persona}`),
  supportRevoke: (supporter: string, recipient: string, persona = currentPersona()) =>
    request<SupportSummary>('/support/revoke', { method: 'POST', body: JSON.stringify({ persona, supporter, recipient }) }),
  setSafetyLimit: (lender: string, borrower: string, limit: number, enabled = true) =>
    request<SafetyLimit>('/safety-net/limits', { method: 'PUT', body: JSON.stringify({ lender, borrower, limit, enabled }) }),
  runSafetyNet: (persona?: string) =>
    request<SafetyDecision[]>(`/safety-net/run${persona ? `?persona=${persona}` : ''}`, { method: 'POST' }),
  approveBridge: (id: string) => request<Bridge>(`/safety-net/bridges/${id}/approve`, { method: 'POST' }),
  declineBridge: (id: string) => request<Bridge>(`/safety-net/bridges/${id}/decline`, { method: 'POST' }),
  // the borrower pays a bridge back early (409 with a plain reason if it isn't safe or isn't out)
  repayBridge: (id: string) => request<Bridge>(`/safety-net/bridges/${id}/repay`, { method: 'POST' }),
  // demo controls: signed-in demo accounts only (Maya, Jordan, Sam)
  demoReset: () => request<DemoStatus>('/demo/reset', { method: 'POST' }),
  demoStatus: () => request<DemoStatus>('/demo/status'),
  // Demo 6: payday comes today — arrives=true deposits a real paycheck first; false = payday is late
  demoPayday: (arrives: boolean) =>
    request<{ lender: string; amount: number; outcome: 'repaid' | 'waiting'; why: string | null }[]>(
      `/demo/payday?arrives=${arrives}`, { method: 'POST' }),
  // the agent answers with this persona's numbers, in the voice for their age
  chat: (message: string, persona = currentPersona()) =>
    request<ChatResponse>('/agent/chat', { method: 'POST', body: JSON.stringify({ message, persona }) }),
  approve: (actionId: string) => request<PendingAction>(`/actions/${actionId}/approve`, { method: 'POST' }),
};

/** A unique id for one Send tap (Hermes has no crypto.randomUUID). Matches the API's ^[A-Za-z0-9-]{8,64}$. */
function tapKey(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

import type {
  ChatResponse,
  Forecast,
  Me,
  P2PPayment,
  P2PRequest,
  P2PSummary,
  Bridge,
  SafetyDecision,
  SafetyLimit,
  SafetyNetSummary,
  DemoStatus,
  PendingAction,
  Persona,
  Recurring,
  Spending,
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
  me: (persona = currentPersona()) => request<Me>(`/me?persona=${persona}`),
  forecast: (days = 30, persona = currentPersona()) => request<Forecast>(`/forecast?days=${days}&persona=${persona}`),
  simulate: (amount: number, date: string, label = 'Purchase', persona = currentPersona()) =>
    request<Forecast>(`/simulate?persona=${persona}`, { method: 'POST', body: JSON.stringify({ amount, date, label }) }),
  recurring: (persona = currentPersona()) => request<Recurring[]>(`/recurring?persona=${persona}`),
  // month = 'YYYY-MM' (defaults to the current month on the server)
  spending: (month?: string, persona = currentPersona()) =>
    request<Spending>(`/spending?persona=${persona}${month ? `&month=${month}` : ''}`),
  // peer-to-peer — amount in dollars (max $1,000 per payment), memo 1–80 chars
  p2p: (persona = currentPersona()) => request<P2PSummary>(`/p2p?persona=${persona}`),
  p2pSend: (contactId: string, amount: number, memo: string, persona = currentPersona()) =>
    request<P2PPayment>('/p2p/send', { method: 'POST', body: JSON.stringify({ persona, contact_id: contactId, amount, memo }) }),
  p2pRequest: (contactId: string, amount: number, memo: string, persona = currentPersona()) =>
    request<P2PRequest>('/p2p/requests', { method: 'POST', body: JSON.stringify({ persona, contact_id: contactId, amount, memo }) }),
  p2pSettle: (requestId: string) => request<P2PRequest>(`/p2p/requests/${requestId}/settle`, { method: 'POST' }),
  // family safety net
  safetyNet: (persona = currentPersona()) => request<SafetyNetSummary>(`/safety-net?persona=${persona}`),
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
  // the agent answers with this persona's numbers, in the voice for their age
  chat: (message: string, persona = currentPersona()) =>
    request<ChatResponse>('/agent/chat', { method: 'POST', body: JSON.stringify({ message, persona }) }),
  approve: (actionId: string) => request<PendingAction>(`/actions/${actionId}/approve`, { method: 'POST' }),
};

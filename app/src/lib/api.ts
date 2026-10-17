import type { ChatResponse, Forecast, Me, PendingAction, Persona, Recurring, Spending } from './types';

// Set EXPO_PUBLIC_API_URL in app/.env. On a physical phone use your laptop's LAN IP
// (e.g. http://192.168.1.20:8000); the Android emulator reaches the laptop at http://10.0.2.2:8000.
const BASE_URL = process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:8000';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  });
  if (!res.ok) throw new Error(`${init?.method ?? 'GET'} ${path} failed: ${res.status}`);
  return res.json() as Promise<T>;
}

export const api = {
  personas: () => request<Persona[]>('/personas'),
  me: (persona = 'maya') => request<Me>(`/me?persona=${persona}`),
  forecast: (days = 30) => request<Forecast>(`/forecast?days=${days}`),
  simulate: (amount: number, date: string, label = 'Purchase') =>
    request<Forecast>('/simulate', { method: 'POST', body: JSON.stringify({ amount, date, label }) }),
  recurring: () => request<Recurring[]>('/recurring'),
  // month = 'YYYY-MM' (defaults to the current month on the server)
  spending: (month?: string, persona = 'maya') =>
    request<Spending>(`/spending?persona=${persona}${month ? `&month=${month}` : ''}`),
  chat: (message: string) =>
    request<ChatResponse>('/agent/chat', { method: 'POST', body: JSON.stringify({ message }) }),
  approve: (actionId: string) => request<PendingAction>(`/actions/${actionId}/approve`, { method: 'POST' }),
};

/**
 * A visitor's own Gemini API key, for Ask Runway. With one set, chat messages carry it in the
 * X-Gemini-Key header and the server answers on their key and quota instead of ours, for that request
 * only (backend/app/agent/chat.py) — Runway never stores it.
 * On the website it lasts as long as the tab (sessionStorage, like the sign-in); in the phone apps, as
 * long as the app is open. Plain module state + useSyncExternalStore, like lib/session.ts.
 */
import { useSyncExternalStore } from 'react';
import { Platform } from 'react-native';

const KEY = 'runway.gemini-key';
// the shape the API accepts (main.GEMINI_KEY); anything else would only come back as a 422
export const looksLikeKey = (k: string) => /^[A-Za-z0-9_-]{20,200}$/.test(k);

let key: string | null = read();
const listeners = new Set<() => void>();

function read(): string | null {
  if (Platform.OS !== 'web') return null;
  try {
    const k = sessionStorage.getItem(KEY);
    return k && looksLikeKey(k) ? k : null;
  } catch {
    return null; // private mode or storage blocked
  }
}

export function setGeminiKey(next: string | null) {
  key = next && looksLikeKey(next) ? next : null;
  if (Platform.OS === 'web') {
    try {
      if (key) sessionStorage.setItem(KEY, key);
      else sessionStorage.removeItem(KEY);
    } catch {
      // storage blocked: the key still works until the page reloads
    }
  }
  listeners.forEach((l) => l());
}

export const getGeminiKey = () => key;

export function useGeminiKey(): string | null {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => key,
    () => key,
  );
}

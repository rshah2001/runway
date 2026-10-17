/**
 * Heads-up alerts on this phone: standard Web Push. The service worker (public/sw.js) shows what the
 * server sends (backend/app/alerts.py): one alert a few days before a dip, no amounts on the lock
 * screen, tap to open Today.
 *
 * iPhone only allows web push for sites added to the Home Screen, so in a Safari tab we say how,
 * instead of failing. Native builds don't use this yet (they would use Expo push notifications).
 */
import { Platform } from 'react-native';

import { api } from './api';

export type PushState =
  | 'on' // this browser is subscribed
  | 'off' // not yet: ask
  | 'denied' // blocked in the browser's settings
  | 'home-screen' // iPhone/iPad in a browser tab: add Runway to the Home Screen first
  | 'unsupported' // this browser (or a native build) can't receive web push
  | 'server-off'; // the server has no push keys configured

function isIos(): boolean {
  const ua = navigator.userAgent;
  return /iPhone|iPad|iPod/.test(ua) || (ua.includes('Macintosh') && navigator.maxTouchPoints > 1);
}

function standalone(): boolean {
  return window.matchMedia?.('(display-mode: standalone)').matches || (navigator as { standalone?: boolean }).standalone === true;
}

/** What this phone can do right now, without asking the user anything. */
export async function pushState(): Promise<PushState> {
  if (Platform.OS !== 'web' || typeof window === 'undefined') return 'unsupported';
  if (!('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)) {
    return isIos() && !standalone() ? 'home-screen' : 'unsupported';
  }
  if (Notification.permission === 'denied') return 'denied';
  const reg = await navigator.serviceWorker.getRegistration('/');
  const sub = await reg?.pushManager.getSubscription();
  return sub && Notification.permission === 'granted' ? 'on' : 'off';
}

/**
 * Ask for permission and subscribe this browser. Call it straight from a button press: Safari only
 * shows the permission prompt in response to a tap, so permission is asked before anything else.
 */
export async function enablePush(): Promise<PushState> {
  const now = await pushState();
  if (now !== 'off' && now !== 'on') return now;
  const permission = await Notification.requestPermission();
  if (permission !== 'granted') return permission === 'denied' ? 'denied' : 'off';
  const { key } = await api.alertsKey();
  if (!key) return 'server-off';
  const reg = await navigator.serviceWorker.register('/sw.js', { scope: '/' });
  await navigator.serviceWorker.ready;
  const sub = (await reg.pushManager.getSubscription())
    ?? (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: fromBase64Url(key) }));
  const json = sub.toJSON();
  if (!json.endpoint || !json.keys?.p256dh || !json.keys?.auth) return 'unsupported';
  await api.pushSubscribe({ endpoint: json.endpoint, p256dh: json.keys.p256dh, auth: json.keys.auth });
  return 'on';
}

/** The VAPID key arrives base64url-encoded; the browser wants the raw bytes. */
function fromBase64Url(s: string): Uint8Array<ArrayBuffer> {
  const b64 = (s + '='.repeat((4 - (s.length % 4)) % 4)).replace(/-/g, '+').replace(/_/g, '/');
  const raw = atob(b64);
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

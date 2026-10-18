/**
 * Light, dark, or whatever the device is set to (Auto, the default).
 *
 * Website: every colour is a CSS variable (constants/runway.ts), so switching only rewrites one
 * attribute on <html>: the whole site, its SVG charts and open menus change together, with nothing
 * re-rendered and no screen losing its place. public/index.html applies the saved choice before the
 * first paint, so a light-mode visitor never sees a dark flash.
 *
 * Phone apps: styles are fixed when the app loads, so the app opens in the right look (your choice,
 * or the phone's setting) and reloads itself, in a blink, when the look should change: when you pick
 * another one, or when you come back to the app after the phone itself switched (Auto). You stay
 * signed in; the session lives in the keychain.
 */
import { useSyncExternalStore } from 'react';
import { AppState, DevSettings, Platform } from 'react-native';
import * as Updates from 'expo-updates';

import { LAUNCH_SCHEME, PALETTES, type Scheme } from '@/constants/runway';
import { type Appearance, deviceScheme, readChoice, resolve, saveChoice } from '@/lib/theme-choice';

export type { Appearance };

const web = Platform.OS === 'web' && typeof document !== 'undefined';
const listeners = new Set<() => void>();
let choice: Appearance = readChoice();

/** The look on screen: web follows the choice live; a phone shows what it launched in until it reloads. */
const scheme = (): Scheme => (web ? resolve(choice) : LAUNCH_SCHEME);

/** One rule per palette: `:root` and `[data-theme=…]` both, so a part of the page can pin its own look. */
function css(): string {
  const vars = (s: Scheme) => Object.entries(PALETTES[s]).map(([k, v]) => `--rw-${k}:${v};`).join('');
  return `:root,[data-theme=dark]{${vars('dark')}color-scheme:dark}[data-theme=light]{${vars('light')}color-scheme:light}`;
}

function applyWeb() {
  const s = scheme();
  document.documentElement.dataset.theme = s;
  // the browser's own bar (phones) matches the page
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', PALETTES[s].bg);
}

/** Phone apps: load again so every style is rebuilt in the new palette. */
function reloadApp() {
  Updates.reloadAsync().catch(() => DevSettings.reload());
}

if (web) {
  const tag = document.createElement('style');
  tag.id = 'rw-theme';
  tag.textContent = css();
  document.head.appendChild(tag);
  applyWeb();
  // Auto: the page follows the device as it changes (sunset, Control Center) while it's open
  window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', () => {
    if (choice !== 'system') return;
    applyWeb();
    listeners.forEach((l) => l());
  });
} else if (Platform.OS !== 'web') {
  // Auto: the phone switched while Runway was open or in the background. Reload when the person is
  // back in the app (never mid-gesture), and only if the look really differs from what's on screen.
  AppState.addEventListener('change', (st) => {
    if (st === 'active' && choice === 'system' && deviceScheme() !== LAUNCH_SCHEME) reloadApp();
  });
}

/** Switch theme. Where the browser can, the old look cross-fades into the new one instead of snapping. */
export function setAppearance(next: Appearance) {
  choice = next;
  saveChoice(next);
  listeners.forEach((l) => l());
  if (web) {
    const doc = document as Document & { startViewTransition?: (cb: () => void) => unknown };
    const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (doc.startViewTransition && !still) doc.startViewTransition(applyWeb);
    else applyWeb();
  } else if (resolve(next) !== LAUNCH_SCHEME) {
    reloadApp();
  }
}

const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => listeners.delete(l);
};

/** The person's choice and the look on screen right now (Auto → light or dark). */
export function useAppearance(): { choice: Appearance; scheme: Scheme } {
  const c = useSyncExternalStore(subscribe, () => choice, () => choice);
  const s = useSyncExternalStore(subscribe, scheme, scheme);
  return { choice: c, scheme: s };
}

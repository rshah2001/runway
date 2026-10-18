/**
 * Light, dark, or whatever the device is set to (the default). The choice is kept in this browser.
 * Every colour in the app is a CSS variable on the website (constants/runway.ts), so switching only
 * rewrites one attribute on <html>: the whole site, its SVG charts and open menus change together,
 * with nothing re-rendered and no screen losing its place. public/index.html applies the saved
 * choice before the first paint, so a light-mode visitor never sees a dark flash.
 * The phone apps keep the charcoal look for now.
 */
import { useSyncExternalStore } from 'react';
import { Platform } from 'react-native';

import { PALETTES, type Scheme } from '@/constants/runway';

export type Appearance = 'system' | 'light' | 'dark';

const KEY = 'runway.appearance';
const web = Platform.OS === 'web' && typeof document !== 'undefined';
const listeners = new Set<() => void>();

/** Storage can be blocked (private windows): then the choice simply lasts until the page reloads. */
function read(): Appearance {
  try {
    const v = localStorage.getItem(KEY);
    return v === 'light' || v === 'dark' ? v : 'system';
  } catch {
    return 'system';
  }
}

let choice: Appearance = web ? read() : 'dark';
const media = web ? window.matchMedia('(prefers-color-scheme: light)') : null;

function scheme(): Scheme {
  if (choice !== 'system') return choice;
  return media?.matches ? 'light' : 'dark';
}

/** One rule per palette: `:root` and `[data-theme=…]` both, so a part of the page can pin its own look. */
function css(): string {
  const vars = (s: Scheme) => Object.entries(PALETTES[s]).map(([k, v]) => `--rw-${k}:${v};`).join('');
  return `:root,[data-theme=dark]{${vars('dark')}color-scheme:dark}[data-theme=light]{${vars('light')}color-scheme:light}`;
}

function apply() {
  const s = scheme();
  document.documentElement.dataset.theme = s;
  // the browser's own bar (phones) matches the page
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', PALETTES[s].bg);
}

if (web) {
  const tag = document.createElement('style');
  tag.id = 'rw-theme';
  tag.textContent = css();
  document.head.appendChild(tag);
  apply();
  // following the device: it changes with the device (sunset, Control Center) while the page is open
  media?.addEventListener('change', () => {
    if (choice !== 'system') return;
    apply();
    listeners.forEach((l) => l());
  });
}

/** Switch theme. Where the browser can, the old look cross-fades into the new one instead of snapping. */
export function setAppearance(next: Appearance) {
  choice = next;
  try {
    if (next === 'system') localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, next);
  } catch {
    // not saved, still applied
  }
  if (web) {
    const doc = document as Document & { startViewTransition?: (cb: () => void) => unknown };
    const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (doc.startViewTransition && !still) doc.startViewTransition(apply);
    else apply();
  }
  listeners.forEach((l) => l());
}

const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => listeners.delete(l);
};

/** The person's choice and the look it comes to right now (System → light or dark). */
export function useAppearance(): { choice: Appearance; scheme: Scheme } {
  const c = useSyncExternalStore(subscribe, () => choice, () => choice);
  const s = useSyncExternalStore(subscribe, scheme, scheme);
  return { choice: c, scheme: s };
}

/**
 * Where the Light / Dark / Auto choice is kept, and what Auto comes to right now. Kept apart from
 * lib/theme.ts because constants/runway.ts needs it while it loads (the phone apps pick their palette
 * once, at launch), and that must not pull in the palettes it is about to define.
 * Website: this browser's localStorage. Phones: the device keychain, read synchronously at launch.
 */
import * as SecureStore from 'expo-secure-store';
import { Appearance as RNAppearance, Platform } from 'react-native';

import type { Scheme } from '@/constants/runway';

export type Appearance = 'system' | 'light' | 'dark';

const KEY = 'runway.appearance';
const web = Platform.OS === 'web';

/** Storage can be blocked (private windows) or missing: then it's Auto. */
export function readChoice(): Appearance {
  try {
    const v = web ? (typeof localStorage === 'undefined' ? null : localStorage.getItem(KEY)) : SecureStore.getItem(KEY);
    return v === 'light' || v === 'dark' ? v : 'system';
  } catch {
    return 'system';
  }
}

export function saveChoice(a: Appearance) {
  try {
    if (web) {
      if (a === 'system') localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, a);
    } else {
      SecureStore.setItem(KEY, a);
    }
  } catch {
    // not saved: it still applies until the page or app reloads
  }
}

/** What the device is set to. */
export function deviceScheme(): Scheme {
  if (web) return typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  return RNAppearance.getColorScheme() === 'light' ? 'light' : 'dark';
}

export const resolve = (a: Appearance): Scheme => (a === 'system' ? deviceScheme() : a);

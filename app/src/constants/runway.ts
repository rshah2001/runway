import { Platform } from 'react-native';

/**
 * Runway design tokens — the WHOOP-inspired charcoal look from app/prototypes/runway.html.
 * One colour per meaning: red = below the floor, green = covered, amber = caution, blue = savings.
 */
export const C = {
  bg: '#14181c',
  bgTop: '#262e36', // top of the page gradient
  card: '#252b31',
  card2: '#2e353c',
  line: '#353d45',
  tabBar: '#111519',
  text: '#ffffff',
  text2: '#a3adb7',
  text3: '#6f7a85',
  red: '#ff5a4e',
  amber: '#f5b83d',
  green: '#3fd07f',
  blue: '#4b9dff',
  slate: '#8fa8c4',
} as const;

/** Pill colours for activity rows, keyed by forecast event kind or spending category. */
export const KIND_COLOR: Record<string, string> = {
  bill: '#5d6f84',
  subscription: '#3e7fd1',
  card_payment: '#c98a1f',
  paycheck: '#249a5c',
  transfer: '#249a5c',
  spending: '#5d6f84',
  other: '#5d6f84',
  Dining: '#c98a1f',
  Shopping: '#8b63d6',
  Gas: '#3e7fd1',
  Groceries: '#249a5c',
  Entertainment: '#c2477a',
  Education: '#5d6f84',
  Subscriptions: '#2b9bb0',
};

/**
 * The platform's own UI font (San Francisco on Apple devices): the easiest to read at every size and
 * age. Used for the plain-language Today screen; Barlow stays for the brand.
 */
export const SYSTEM_FONT = Platform.select({
  ios: 'System',
  android: 'sans-serif',
  default: '-apple-system, BlinkMacSystemFont, "SF Pro Text", Inter, system-ui, sans-serif',
});

/** Font family names registered in the root layout via @expo-google-fonts. */
export const F = {
  body: 'Barlow_400Regular',
  bodyMedium: 'Barlow_500Medium',
  bodySemi: 'Barlow_600SemiBold',
  cond: 'BarlowCondensed_600SemiBold',
  condMedium: 'BarlowCondensed_500Medium',
  condBold: 'BarlowCondensed_700Bold',
} as const;

export const RADIUS = 14;

/** Width at which the website switches to the two-column desktop layout. */
export const WIDE = 960;
/** Content never grows wider than this on desktop. */
export const MAX_WIDTH = 1120;

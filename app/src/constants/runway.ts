import { Platform } from 'react-native';

/**
 * Runway design tokens: the WHOOP-inspired charcoal look (dark) and a calm paper-white twin (light).
 * One colour per meaning: red = below the floor, green = covered, amber = caution, blue = savings.
 * Light keeps the same meanings, a shade deeper so they still read on white.
 */
const DARK = {
  bg: '#0f1215',
  bgTop: '#15191d', // top of the page gradient (a shade darker than the cards, so they stand out)
  bgMid: '#12161a',
  card: '#1b2024',
  card2: '#252b30',
  line: '#2a3035',
  line2: '#2f363c', // outlines of buttons and inputs: a touch stronger than dividers
  grab: '#3a4147', // sheet handles, empty check circles
  hover: 'rgba(255,255,255,0.05)',
  tabBar: '#0f1215',
  glass: 'rgba(32,37,41,0.92)', // the floating pill bar
  glassLine: 'rgba(255,255,255,0.08)',
  text: '#ffffff',
  text2: '#a7b0b8',
  text3: '#6f7a85',
  /** the one solid button per screen, and what's written on it */
  primary: '#ffffff',
  onPrimary: '#111111',
  red: '#ff6b5e',
  amber: '#f5b83d',
  green: '#46d483',
  blue: '#4b9dff',
  cover: '#7cb8ff', // "you can cover them" in Circles
  slate: '#8fa8c4',
};

const LIGHT: typeof DARK = {
  bg: '#f2f3f5',
  bgTop: '#fbfbfc',
  bgMid: '#f6f7f8',
  card: '#ffffff',
  card2: '#eef0f2',
  line: '#e3e6e9',
  line2: '#d4d9de',
  grab: '#c6ccd2',
  hover: 'rgba(15,18,21,0.05)',
  tabBar: '#f2f3f5',
  glass: 'rgba(255,255,255,0.9)',
  glassLine: 'rgba(15,18,21,0.08)',
  text: '#111418',
  text2: '#59636d',
  text3: '#89929b',
  primary: '#111418',
  onPrimary: '#ffffff',
  red: '#e0473a',
  amber: '#b7790a',
  green: '#1c9a54',
  blue: '#1f78e0',
  cover: '#2f7fd8',
  slate: '#5a7491',
};

export type Palette = typeof DARK;
export type Scheme = 'dark' | 'light';
export const PALETTES: Record<Scheme, Palette> = { dark: DARK, light: LIGHT };

/**
 * The colours every style uses. On the website each one is a CSS variable (`var(--rw-bg)`), so the
 * whole site switches theme at once, styles and SVG included, without re-rendering anything
 * (lib/theme.ts writes the variables). The phone apps stay on the charcoal look for now.
 */
export const C: Palette = Platform.OS === 'web'
  ? (Object.fromEntries(Object.keys(DARK).map((k) => [k, `var(--rw-${k})`])) as Palette)
  : DARK;

/**
 * A see-through version of a colour (`hex` is the alpha byte, as in `#ff6b5e22`). A theme colour is a
 * CSS variable on the website, so it can't take a suffix: it's mixed with transparent instead. The
 * leading `var(--rw-none, …)` is only there because react-native-web accepts colours that start "var(".
 */
export function alpha(color: string, hex: string): string {
  if (!color.startsWith('var(')) return `${color}${hex}`;
  return `var(--rw-none, color-mix(in srgb, ${color} ${Math.round((parseInt(hex, 16) / 255) * 100)}%, transparent))`;
}

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

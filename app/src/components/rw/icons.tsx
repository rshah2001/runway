// Monochrome line icons (20×20 grid, stroked) — quieter than emoji and identical on every platform.
import Svg, { Circle, Defs, LinearGradient, Path, Rect, Stop } from 'react-native-svg';

import { C } from '@/constants/runway';

type P = { size?: number; color?: string };
const base = (size: number, color: string) => ({
  width: size, height: size, viewBox: '0 0 20 20', fill: 'none', stroke: color,
  strokeWidth: 1.7, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const,
});

const ICONS: Record<string, (p: Required<P>) => React.ReactElement> = {
  bill: ({ size, color }) => <Svg {...base(size, color)}><Path d="M5 2.5h10v15l-2.5-1.5-2.5 1.5-2.5-1.5L5 17.5z" /><Path d="M8 7h4M8 10h4" /></Svg>,
  subscription: ({ size, color }) => <Svg {...base(size, color)}><Rect x="2.5" y="4" width="15" height="10" rx="2" /><Path d="M7 17h6" /></Svg>,
  card_payment: ({ size, color }) => <Svg {...base(size, color)}><Rect x="2" y="4.5" width="16" height="11" rx="2" /><Path d="M2 8.5h16" /></Svg>,
  paycheck: ({ size, color }) => <Svg {...base(size, color)}><Path d="M10 3v14M13.5 6.5c0-1.5-1.5-2.5-3.5-2.5s-3.5 1-3.5 2.5 1.5 2.3 3.5 2.8 3.5 1.3 3.5 2.9-1.5 2.8-3.5 2.8-3.5-1-3.5-2.5" /></Svg>,
  transfer: ({ size, color }) => <Svg {...base(size, color)}><Path d="M4 7h11l-3-3M16 13H5l3 3" /></Svg>,
  spending: ({ size, color }) => <Svg {...base(size, color)}><Path d="M3 4h2l1.6 8.5h8.4L17 6H6" /><Circle cx="8" cy="16" r="1" /><Circle cx="14" cy="16" r="1" /></Svg>,
  Groceries: ({ size, color }) => <Svg {...base(size, color)}><Path d="M3 4h2l1.6 8.5h8.4L17 6H6" /><Circle cx="8" cy="16" r="1" /><Circle cx="14" cy="16" r="1" /></Svg>,
  Dining: ({ size, color }) => <Svg {...base(size, color)}><Path d="M6 2.5v6a2 2 0 0 0 4 0v-6M8 8.5v9M14.5 17.5v-15c-2 1-3 3.5-3 6.5h3" /></Svg>,
  Gas: ({ size, color }) => <Svg {...base(size, color)}><Path d="M4 17.5v-13a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v13M3 17.5h10M4.5 8h7M12 7.5l3 2.5v5a1.2 1.2 0 0 0 2.4 0V8L15 5.5" /></Svg>,
  Shopping: ({ size, color }) => <Svg {...base(size, color)}><Path d="M4 6.5h12l-1 11H5zM7.5 6.5a2.5 2.5 0 0 1 5 0" /></Svg>,
  Entertainment: ({ size, color }) => <Svg {...base(size, color)}><Path d="M3 8a2 2 0 0 0 0 4v4h14v-4a2 2 0 0 1 0-4V4H3z" /></Svg>,
  Education: ({ size, color }) => <Svg {...base(size, color)}><Path d="M3 4.5h5a2 2 0 0 1 2 2v10a1.5 1.5 0 0 0-1.5-1.5H3zM17 4.5h-5a2 2 0 0 0-2 2v10a1.5 1.5 0 0 1 1.5-1.5H17z" /></Svg>,
  Subscriptions: ({ size, color }) => <Svg {...base(size, color)}><Path d="M4 8a6 6 0 0 1 10.5-3.5L16 6M16 2.5V6h-3.5M16 12a6 6 0 0 1-10.5 3.5L4 14M4 17.5V14h3.5" /></Svg>,
  shield: ({ size, color }) => <Svg {...base(size, color)}><Path d="M10 2.5l6 2.5v5c0 3.7-2.5 6.3-6 7.5-3.5-1.2-6-3.8-6-7.5V5z" /></Svg>,
  check: ({ size, color }) => <Svg {...base(size, color)}><Path d="M5 10.5l3.5 3.5L15 7" /></Svg>,
  close: ({ size, color }) => <Svg {...base(size, color)}><Path d="M6 6l8 8M14 6l-8 8" /></Svg>,
  send: ({ size, color }) => <Svg {...base(size, color)} strokeWidth={2.2}><Path d="M10 16V4M5 9l5-5 5 5" /></Svg>,
  tool: ({ size, color }) => <Svg {...base(size, color)} strokeWidth={2}><Path d="M12.5 3.5a4 4 0 0 0-5 5L3 13l4 4 4.5-4.5a4 4 0 0 0 5-5L14 10l-4-4z" /></Svg>,
};

/** Icon by name (event kind, spending category, or UI glyph); falls back to a receipt. */
export function Icon({ name, size = 18, color = C.text }: P & { name: string }) {
  const Draw = ICONS[name] ?? ICONS.bill;
  return <Draw size={size} color={color} />;
}

/**
 * The Runway logo: the forecast curve (white → coral → green) on the indigo-to-magenta badge — the same
 * mark as public/runway-logo.svg. `size` is kept from the old swoosh API (it was ~22): the badge is drawn
 * `size × 1.1` tall and 2.125× as wide, so every existing call site gets the new logo at a matching scale.
 */
export function Swoosh({ size = 22 }: P) {
  const h = size * 1.1;
  return (
    <Svg width={h * 2.125} height={h} viewBox="0 0 340 160" accessibilityLabel="Runway">
      <Defs>
        <LinearGradient id="rwBg" x1="0" y1="1" x2="1" y2="0">
          <Stop offset="0" stopColor="#12366d" /><Stop offset=".5" stopColor="#20112e" /><Stop offset="1" stopColor="#692055" />
        </LinearGradient>
        <LinearGradient id="rwLine" x1="0" y1="0" x2="1" y2="0">
          <Stop offset="0" stopColor="#fff" /><Stop offset=".54" stopColor="#fb625b" /><Stop offset=".75" stopColor="#fb625b" /><Stop offset=".76" stopColor="#42e1a1" />
        </LinearGradient>
      </Defs>
      <Rect width={340} height={160} rx={34} fill="url(#rwBg)" />
      <Path d="M15 50 C75 48 67 86 135 82 S180 142 223 130 S238 53 276 56 S320 66 338 40" fill="none" stroke="#bd91ed" strokeOpacity={0.35} strokeWidth={11} />
      <Path d="M15 50 C75 48 67 86 135 82 S180 142 223 130 S238 53 276 56 S320 66 338 40" fill="none" stroke="url(#rwLine)" strokeWidth={5} strokeLinecap="round" />
      <Path d="M0 118 H340" stroke="#d3badf" strokeWidth={1.5} strokeDasharray="3 5" strokeOpacity={0.3} />
      <Circle cx={217} cy={131} r={6} fill="#fc615c" />
    </Svg>
  );
}

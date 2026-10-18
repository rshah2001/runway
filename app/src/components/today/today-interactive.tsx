/**
 * The 30-day balance line you can touch (used by Today, components/today/today-home.tsx):
 *  - scrub: drag (or hover, on the website) across it — a cursor follows 1:1, snaps to each day with
 *    a light haptic tick on phones, and reports the day so the screen can show that day's balance;
 *  - what if: the line slides down on a spring by the amount being tried;
 *  - the fix: while a suggestion waits, a ghost line shows the balance after it; approve, and the
 *    line morphs to the real new numbers.
 *
 * Motion follows Apple's rules: critically damped springs that start from the current on-screen
 * value (so every move can be interrupted), haptics only on meaningful snaps. Reduced motion: values
 * change in place. Every number comes from the forecast.
 */
import * as Haptics from 'expo-haptics';
import { useEffect, useMemo, useRef, useState } from 'react';
import { type GestureResponderEvent, type LayoutChangeEvent, Platform, StyleSheet, View } from 'react-native';
import Animated, {
  Easing,
  type SharedValue,
  useAnimatedProps,
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withDelay,
  withSpring,
  withTiming,
} from 'react-native-reanimated';
import Svg, { Circle, ClipPath, Defs, G, Line, LinearGradient, Path, Rect, Stop, Text as SvgText } from 'react-native-svg';

import { T } from '@/components/rw/ui';
import { C, F, RADIUS, SYSTEM_FONT } from '@/constants/runway';
import { money, monthDay, weekdayDate } from '@/lib/format';
import { zoom } from '@/lib/zoom';
import type { Forecast } from '@/lib/types';

// Apple's default: critically damped, no overshoot. `duration` stands in for "response".
const SNAP = { dampingRatio: 1, duration: 180 }; // cursor gliding between days while scrubbing
const MOVE = { dampingRatio: 1, duration: 450 }; // cursor jumping to a row's day; the line moving
const WHAT_IFS = [20, 50, 100];

/* ---------------- the chart ---------------- */

const CH = 210;
const PAD = { top: 24, bottom: 24, left: 8, right: 8 };
const AnimatedPath = Animated.createAnimatedComponent(Path);
const AnimatedLine = Animated.createAnimatedComponent(Line);
const AnimatedCircle = Animated.createAnimatedComponent(Circle);

/** The line's values right now: mid-morph between old and new numbers, plus the what-if slide. */
function blend(a: number[], b: number[], p: number, o: number): number[] {
  'worklet';
  return a.map((v, i) => v + (b[i] - v) * p + o);
}

/** Build "M x,y L …" for values on the chart (worklet: runs on the UI thread every frame). */
function linePath(vals: number[], w: number, lo: number, span: number): string {
  'worklet';
  const n = vals.length, dx = (w - PAD.left - PAD.right) / (n - 1), h = CH - PAD.top - PAD.bottom;
  let d = '';
  for (let i = 0; i < n; i++) d += `${i ? 'L' : 'M'}${PAD.left + i * dx},${PAD.top + (1 - (vals[i] - lo) / span) * h} `;
  return d;
}

/**
 * The 30-day balance line (shared by both Today layouts). `takeoff`: bump it after an approval that
 * covers every dip, and once the line has moved up a plane rolls along the cushion line and lifts off.
 */
export function BalanceChart({ f, spend, ghost, focusIndex, onScrub, takeoff = 0, hint = true }: {
  f: Forecast; spend: number; ghost: number | null; focusIndex: number | null; onScrub: (i: number | null) => void;
  takeoff?: number; hint?: boolean;
}) {
  const reduced = useReducedMotion();
  const [w, setW] = useState(0);
  const n = f.points.length;
  const base = useMemo(() => f.points.map((p) => p.balance), [f.points]);

  // A fixed scale that leaves room for every preview, so moving the line never rescales the chart.
  const top = Math.max(...base, f.safe_floor) + Math.max(0, f.safe_floor - f.low.balance) + 60;
  const bottom = Math.min(...base, f.safe_floor) - Math.max(...WHAT_IFS, spend); // room for a custom what-if too
  const lo = bottom - (top - bottom) * 0.06, span = Math.max(top - lo, 1);
  const yOf = (v: number) => PAD.top + (1 - (v - lo) / span) * (CH - PAD.top - PAD.bottom);
  const xOf = (i: number) => PAD.left + (i / (n - 1)) * (w - PAD.left - PAD.right);
  const floorY = yOf(f.safe_floor);

  // The line morphs between old and new numbers (after an approval) and slides with the what-if.
  const from = useSharedValue(base), to = useSharedValue(base), morph = useSharedValue(1);
  const offset = useSharedValue(0);
  const shown = useRef(base);
  useEffect(() => {
    if (shown.current === base) return;
    from.set(shown.current); // start from the line that's on screen
    to.set(base);
    shown.current = base;
    if (reduced) morph.set(1);
    else {
      morph.set(0);
      morph.set(withSpring(1, MOVE));
    }
  }, [base, reduced, from, to, morph]);
  useEffect(() => {
    offset.set(reduced ? -spend : withSpring(-spend, MOVE));
  }, [spend, reduced, offset]);

  // every worklet reads the shared values itself, so each one re-runs the moment any of them moves
  const yIn = (v: number) => {
    'worklet';
    return PAD.top + (1 - (v - lo) / span) * (CH - PAD.top - PAD.bottom);
  };
  const lineProps = useAnimatedProps(() => ({ d: linePath(blend(from.get(), to.get(), morph.get(), offset.get()), w, lo, span) }));
  const toAxis = useAnimatedProps(() => ({
    d: `${linePath(blend(from.get(), to.get(), morph.get(), offset.get()), w, lo, span)} L${w - PAD.right},${CH - PAD.bottom} L${PAD.left},${CH - PAD.bottom} Z`,
  }));
  const toFloor = useAnimatedProps(() => ({
    d: `${linePath(blend(from.get(), to.get(), morph.get(), offset.get()), w, lo, span)} L${w - PAD.right},${floorY} L${PAD.left},${floorY} Z`,
  }));
  const todayDot = useAnimatedProps(() => ({ cy: yIn(blend(from.get(), to.get(), morph.get(), offset.get())[0]) }));

  // Ghost: the balance after the proposed fix, fading in while the suggestion waits.
  const ghostOn = useSharedValue(0);
  useEffect(() => {
    ghostOn.set(reduced ? (ghost ? 1 : 0) : withTiming(ghost ? 1 : 0, { duration: 260 }));
  }, [ghost, reduced, ghostOn]);
  const ghostProps = useAnimatedProps(() => ({ opacity: ghostOn.get() }));
  const ghostD = w > 0 && ghost ? linePath(base.map((v) => v + ghost), w, lo, span) : '';

  // The cursor: glued to the pointer while scrubbing (snapping to days), springs to a row's day.
  const cx = useSharedValue(0), cOn = useSharedValue(0), cIdx = useSharedValue(0);
  const scrubbing = useRef(false);
  const last = useRef<number | null>(null);
  const place = (i: number, spring: typeof SNAP) => {
    cIdx.set(i);
    cx.set(reduced ? xOf(i) : withSpring(xOf(i), spring));
    cOn.set(reduced ? 1 : withTiming(1, { duration: 90 }));
  };
  const hide = () => cOn.set(reduced ? 0 : withTiming(0, { duration: 200 }));
  useEffect(() => {
    if (scrubbing.current || w === 0) return;
    if (focusIndex !== null) place(focusIndex, MOVE);
    else hide();
    // place/hide only read stable values; re-run when the pointed-at row or the width changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusIndex, w]);

  function at(px: number) {
    if (w === 0) return;
    const i = Math.max(0, Math.min(n - 1, Math.round(((px - PAD.left) / (w - PAD.left - PAD.right)) * (n - 1))));
    place(i, SNAP);
    if (i !== last.current) {
      last.current = i;
      onScrub(i);
      if (Platform.OS !== 'web') Haptics.selectionAsync().catch(() => {}); // a tick per day, like a picker
    }
  }
  function end() {
    scrubbing.current = false;
    last.current = null;
    onScrub(null);
    if (focusIndex === null) hide();
  }

  const cursorLine = useAnimatedProps(() => ({ x1: cx.get(), x2: cx.get(), opacity: cOn.get() }));
  const cursorDot = useAnimatedProps(() => {
    const v = blend(from.get(), to.get(), morph.get(), offset.get())[Math.round(cIdx.get())];
    return { cx: cx.get(), cy: yIn(v), opacity: cOn.get(), fill: v < f.safe_floor ? C.red : C.text };
  });

  const lowI = f.points.findIndex((p) => p.date === f.low.date);
  const dipping = f.low.balance - spend < f.safe_floor;
  const lineColor = dipping ? C.text : C.green; // the line turns green once every day clears the cushion

  // Takeoff: the cushion line is the runway. The plane rolls along it and lifts off after ~55% of the roll.
  const fly = useSharedValue(0);
  const lastTakeoff = useRef(takeoff);
  useEffect(() => {
    if (takeoff === lastTakeoff.current) return;
    lastTakeoff.current = takeoff;
    if (reduced) return;
    fly.set(0);
    fly.set(withDelay(500, withTiming(1, { duration: 1400, easing: Easing.inOut(Easing.quad) })));
  }, [takeoff, reduced, fly]);
  const plane = useAnimatedStyle(() => {
    const t = fly.get(), lift = Math.pow(Math.max(0, (t - 0.55) / 0.45), 2);
    return {
      opacity: t <= 0 || t >= 1 ? 0 : t < 0.08 ? t / 0.08 : t > 0.85 ? (1 - t) / 0.15 : 1,
      transform: [{ translateX: PAD.left + t * (w - PAD.left - PAD.right) - 13 }, { translateY: floorY - 14 - lift * 90 }, { rotate: `${90 - lift * 30}deg` }],
    };
  });
  const pays = f.events.filter((e) => e.kind === 'paycheck').map((e) => f.points.findIndex((p) => p.date === e.date)).filter((i) => i > 0);
  const anchor = lowI > n * 0.75 ? 'end' : lowI < n * 0.25 ? 'start' : 'middle';

  // pointer handlers: press-down starts tracking at once (no movement threshold needed on a chart)
  const touch = {
    onStartShouldSetResponder: () => true,
    onMoveShouldSetResponder: () => true,
    onResponderTerminationRequest: () => false, // keep the finger until it lifts
    onResponderGrant: (e: GestureResponderEvent) => { scrubbing.current = true; at(e.nativeEvent.locationX / zoom()); },
    onResponderMove: (e: GestureResponderEvent) => at(e.nativeEvent.locationX / zoom()),
    onResponderRelease: end,
    onResponderTerminate: end,
  };
  const hover = Platform.OS === 'web'
    ? {
      onPointerMove: (e: { nativeEvent: { offsetX?: number; pointerType?: string } }) => {
        if (e.nativeEvent.pointerType === 'mouse' && e.nativeEvent.offsetX !== undefined) at(e.nativeEvent.offsetX / zoom()); // on-screen px → layout px
      },
      onPointerLeave: () => { if (!scrubbing.current) end(); },
    }
    : {};

  return (
    <View style={{ marginTop: 6 }}>
      <View onLayout={(e: LayoutChangeEvent) => setW(e.nativeEvent.layout.width)} style={{ height: CH }}
        accessible accessibilityRole="adjustable"
        accessibilityLabel={`Your balance over the next 30 days. Lowest ${money(f.low.balance - spend, 0)} on ${weekdayDate(f.low.date)}. Drag across to see each day.`}>
        {w > 0 && (
          <Svg width={w} height={CH} pointerEvents="none">
            <Defs>
              <LinearGradient id="fillUp" x1="0" y1="0" x2="0" y2="1">
                <Stop offset="0" stopColor={lineColor} stopOpacity={0.14} />
                <Stop offset="1" stopColor={C.text} stopOpacity={0} />
              </LinearGradient>
              <ClipPath id="above"><Rect x={0} y={0} width={w} height={floorY} /></ClipPath>
              <ClipPath id="below"><Rect x={0} y={floorY} width={w} height={CH - floorY} /></ClipPath>
            </Defs>
            <G clipPath="url(#above)"><AnimatedPath fill="url(#fillUp)" animatedProps={toAxis} /></G>
            <G clipPath="url(#below)"><AnimatedPath fill={C.red} fillOpacity={0.4} animatedProps={toFloor} /></G>
            <Line x1={0} x2={w} y1={floorY} y2={floorY} stroke={C.text3} strokeWidth={1} strokeDasharray="4 5" />
            <SvgText x={w - 4} y={floorY - 7} fill={C.text3} fontSize={12} fontFamily={F.body} textAnchor="end">
              {`${money(f.safe_floor, 0)} cushion`}
            </SvgText>
            {ghostD ? (
              <AnimatedPath d={ghostD} fill="none" stroke={C.green} strokeWidth={2} strokeDasharray="6 6" strokeLinecap="round" animatedProps={ghostProps} />
            ) : null}
            <G clipPath="url(#above)"><AnimatedPath fill="none" stroke={lineColor} strokeWidth={2.5} strokeLinejoin="round" animatedProps={lineProps} /></G>
            <G clipPath="url(#below)"><AnimatedPath fill="none" stroke={C.red} strokeWidth={2.5} strokeLinejoin="round" animatedProps={lineProps} /></G>
            {pays.map((i) => (
              <RidingDot key={i} i={i} x={xOf(i)} from={from} to={to} morph={morph} offset={offset} yIn={yIn} />
            ))}
            <AnimatedCircle cx={xOf(0)} r={5} fill={C.text} animatedProps={todayDot} />
            {lowI >= 0 && dipping && (
              <RidingLabel i={lowI} x={xOf(lowI)} from={from} to={to} morph={morph} offset={offset} yIn={yIn} anchor={anchor}
                text={`${money(f.low.balance - spend, 0)} on ${monthDay(f.low.date)}`} />
            )}
            <AnimatedLine y1={PAD.top - 8} y2={CH - PAD.bottom} stroke={C.text} strokeOpacity={0.5} strokeWidth={1} animatedProps={cursorLine} />
            <AnimatedCircle r={6} stroke={C.card} strokeWidth={2.5} animatedProps={cursorDot} />
          </Svg>
        )}
        <Animated.View pointerEvents="none" style={[s.plane, plane]}>
          <Svg width={26} height={26} viewBox="0 0 24 24" fill={C.text}>
            <Path d="M21 16v-2l-8-5V3.5a1.5 1.5 0 0 0-3 0V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5z" />
          </Svg>
        </Animated.View>
        {/* the touch layer sits on top of the drawing */}
        <View style={StyleSheet.absoluteFill} {...touch} {...hover} />
      </View>
      <View style={s.axis}>
        <T tone="dim" style={s.axisText}>Today</T>
        <View style={s.legend}>
          <View style={[s.legendDot, { backgroundColor: C.green }]} /><T tone="dim" style={s.axisText}>Payday</T>
          {ghost ? <><View style={[s.legendDash]} /><T tone="dim" style={s.axisText}>After the fix</T></> : null}
        </View>
        <T tone="dim" style={s.axisText}>{monthDay(f.points[n - 1].date)}</T>
      </View>
      {hint && <T tone="faint" style={s.hint}>{Platform.OS === 'web' ? 'Point at the line to see any day.' : 'Drag along the line to see any day.'}</T>}
    </View>
  );
}

type Ride = {
  i: number; x: number; from: SharedValue<number[]>; to: SharedValue<number[]>;
  morph: SharedValue<number>; offset: SharedValue<number>; yIn: (v: number) => number;
};
const AnimatedSvgText = Animated.createAnimatedComponent(SvgText);

/** A payday dot that rides the line as it moves. */
function RidingDot({ i, x, from, to, morph, offset, yIn }: Ride) {
  const props = useAnimatedProps(() => ({ cy: yIn(blend(from.get(), to.get(), morph.get(), offset.get())[i]) }));
  return <AnimatedCircle cx={x} r={4.5} fill={C.green} animatedProps={props} />;
}

/** The low-point label, riding just under the line. */
function RidingLabel({ i, x, from, to, morph, offset, yIn, anchor, text }: Ride & { anchor: 'start' | 'middle' | 'end'; text: string }) {
  const props = useAnimatedProps(() => ({ y: Math.min(CH - 4, yIn(blend(from.get(), to.get(), morph.get(), offset.get())[i]) + 22) }));
  return (
    <AnimatedSvgText x={x} fill={C.red} fontSize={13} fontFamily={SYSTEM_FONT} fontWeight="600" textAnchor={anchor} animatedProps={props}>
      {text}
    </AnimatedSvgText>
  );
}

const SYS = { fontFamily: SYSTEM_FONT } as const;
const s = StyleSheet.create({
  wideRow: { flexDirection: 'row', gap: 18, alignItems: 'flex-start' },

  hero: { alignItems: 'center', paddingTop: 18, paddingBottom: 4 },
  hello: { ...SYS, fontSize: 26, fontWeight: '700', letterSpacing: -0.4, color: C.text },
  date: { ...SYS, fontSize: 14, color: C.text2, marginTop: 4 },
  balLabel: { ...SYS, fontSize: 13, color: C.text2, marginTop: 22 },
  bal: { ...SYS, fontSize: 60, lineHeight: 66, fontWeight: '800', letterSpacing: -1.8, color: C.text, fontVariant: ['tabular-nums'], marginTop: 2 },
  subline: { ...SYS, fontSize: 14, color: C.text2, minHeight: 20 },
  pill: { flexDirection: 'row', alignItems: 'center', gap: 7, borderRadius: 99, paddingVertical: 6, paddingHorizontal: 14, marginTop: 10 },
  pillDot: { width: 8, height: 8, borderRadius: 4 },
  pillText: { ...SYS, fontSize: 14, fontWeight: '700' },

  tiles: { flexDirection: 'row', gap: 10 },
  tile: { flex: 1, padding: 16 },
  tileLabel: { ...SYS, fontSize: 13, color: C.text2 },
  tileValue: { ...SYS, fontSize: 26, fontWeight: '700', letterSpacing: -0.5, color: C.text, fontVariant: ['tabular-nums'], marginTop: 6 },
  tileSub: { ...SYS, fontSize: 12.5, lineHeight: 17, color: C.text3, marginTop: 2 },

  glass: { backgroundColor: C.card, borderWidth: 1, borderColor: C.line, borderRadius: RADIUS + 4, padding: 22 },
  cardTitle: { ...SYS, fontSize: 19, fontWeight: '600', color: C.text },

  callout: { borderLeftWidth: 3, borderRadius: 10, paddingVertical: 12, paddingHorizontal: 16 },
  actionRow: { flexDirection: 'row', alignItems: 'center', gap: 14 },
  action: { alignSelf: 'flex-start', height: 40, paddingHorizontal: 18, borderRadius: 20, backgroundColor: C.primary, alignItems: 'center', justifyContent: 'center' },
  actionGhost: { backgroundColor: 'transparent', borderWidth: 1, borderColor: C.line2 },
  actionText: { ...SYS, fontSize: 15, fontWeight: '600', color: C.onPrimary },
  cancel: { ...SYS, fontSize: 15, color: C.text2 },
  twoActions: { flexDirection: 'row', gap: 10, marginTop: 10 },
  noteText: { ...SYS, fontSize: 14, lineHeight: 20, color: C.text2, marginTop: 8 },
  limitBox: { borderRadius: 10, paddingVertical: 12, paddingHorizontal: 16, backgroundColor: C.hover, borderWidth: 1, borderColor: C.line },
  demo: { alignItems: 'center', marginTop: 8 },
  calloutTitle: { ...SYS, fontSize: 16, fontWeight: '700', color: C.text },
  calloutText: { ...SYS, fontSize: 15, lineHeight: 22, color: C.text2, marginTop: 3 },

  axis: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginTop: 2 },
  axisText: { ...SYS, fontSize: 13 },
  legend: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  legendDot: { width: 9, height: 9, borderRadius: 5 },
  legendDash: { width: 16, height: 0, borderTopWidth: 2, borderStyle: 'dashed', borderColor: C.green, marginLeft: 10 },
  hint: { ...SYS, fontSize: 13, marginTop: 6 },
  plane: { position: 'absolute', left: 0, top: 0, width: 26, height: 26 },

  whatIf: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 12, marginTop: 18 },
  whatIfLabel: { ...SYS, fontSize: 15 },
  chips: { flexDirection: 'row', gap: 8 },
  chip: { height: 36, paddingHorizontal: 16, borderRadius: 18, borderWidth: 1, borderColor: C.line2, backgroundColor: C.hover, alignItems: 'center', justifyContent: 'center' },
  chipOn: { backgroundColor: C.primary, borderColor: C.primary },
  chipText: { ...SYS, fontWeight: '600', fontSize: 15, color: C.text },
  chipTextOn: { color: C.onPrimary },
});

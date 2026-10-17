/**
 * Today, option A, interactive. One question answered first ("am I okay?"), then a balance line you
 * can touch:
 *  - scrub: drag (or hover, on the website) across the chart — a cursor follows 1:1, snaps to each
 *    day with a light haptic tick on phones, and the big number and sentence switch to that day;
 *  - Coming up rows point at their day on the chart (hover/press), and light up while you scrub it;
 *  - what if: tap $20 / $50 / $100 and the line slides down on a spring to show spending it today;
 *  - the fix: while a suggestion waits, a ghost line shows the balance after it; approve, and the
 *    line springs up to the real new numbers.
 *  - 3D: cards tilt up into place as they arrive (on load, and as you scroll them into view), and
 *    the main card lifts when the dip is covered.
 *
 * Motion follows Apple's rules: feedback on press-down, critically damped springs that start from
 * the current on-screen value (so every move can be interrupted), haptics only on meaningful snaps.
 * Reduced motion: no tilts or slides; values change in place. Every number comes from the forecast.
 */
import * as Haptics from 'expo-haptics';
import { type PropsWithChildren, useEffect, useMemo, useRef, useState } from 'react';
import { type GestureResponderEvent, type LayoutChangeEvent, Platform, Pressable, StyleSheet, Text, View } from 'react-native';
import Animated, {
  type SharedValue,
  useAnimatedProps,
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withDelay,
  withSequence,
  withSpring,
  withTiming,
} from 'react-native-reanimated';
import Svg, { Circle, ClipPath, Defs, G, Line, LinearGradient, Path, Rect, Stop, Text as SvgText } from 'react-native-svg';

import { answer, ComingUp, Fix } from '@/components/today/today-options';
import { T } from '@/components/rw/ui';
import { C, F, RADIUS } from '@/constants/runway';
import { money, monthDay, weekdayDate } from '@/lib/format';
import { isClear } from '@/lib/runway';
import type { Forecast } from '@/lib/types';

// Apple's default: critically damped, no overshoot. `duration` stands in for "response".
const SNAP = { dampingRatio: 1, duration: 180 }; // cursor gliding between days while scrubbing
const MOVE = { dampingRatio: 1, duration: 450 }; // cursor jumping to a row's day; the line moving
const LIFT = { dampingRatio: 0.8, duration: 500 }; // the covered card lifting (earned: the user approved)
const WHAT_IFS = [20, 50, 100];

/** The forecast as it would be with `delta` more (or less) in checking from today on. */
function shifted(f: Forecast, delta: number): Forecast {
  if (!delta) return f;
  const points = f.points.map((p) => ({ ...p, balance: p.balance + delta }));
  const low = points.reduce((m, p) => (p.balance < m.balance ? p : m), points[0]);
  return { ...f, points, low };
}

export function TodayInteractive({ f, wide, scrollY, viewport }: {
  f: Forecast; wide: boolean; scrollY?: SharedValue<number>; viewport?: number;
}) {
  const [spend, setSpend] = useState(0); // what-if amount, 0 = off
  const [ghost, setGhost] = useState<number | null>(null); // a proposed fix, previewed on the chart
  const [scrub, setScrub] = useState<number | null>(null); // day index under the finger/pointer
  const [rowDate, setRowDate] = useState<string | null>(null); // day pointed at from Coming up

  const view = shifted(f, -spend);
  const a = answer(view);
  const focusIndex = rowDate ? f.points.findIndex((p) => p.date === rowDate) : null;
  const day = scrub ?? (focusIndex !== null && focusIndex >= 0 ? focusIndex : null);
  const point = day !== null ? view.points[day] : null;
  const dayEvents = point ? f.events.filter((e) => e.date === point.date && e.kind !== 'spending') : [];

  const covered = isClear(f);
  const hero = (
    <Reveal3D order={0} scrollY={scrollY} viewport={viewport} lift={covered}>
      <View style={s.hero}>
        {/* the number follows the cursor: today's balance, or the scrubbed day's */}
        <T tone="dim" style={s.kicker} accessibilityLiveRegion="polite">
          {point && day ? weekdayDate(point.date) : spend ? `If you spend ${money(spend, 0)} today` : 'In checking today'}
        </T>
        <Text style={[s.balance, point && point.balance < f.safe_floor && { color: C.red }]}>
          {money(point ? point.balance : view.points[0].balance, 0)}
        </Text>
        <T tone="dim" style={s.dayLine}>
          {point && day
            ? dayEvents.length
              ? dayEvents.map((e) => `${e.label} ${e.amount > 0 ? '+' : '−'}${money(Math.abs(e.amount), 0)}`).join(' · ')
              : 'Everyday spending only'
            : ' '}
        </T>
        <Text style={[s.title, covered && !spend && { color: C.green }]}>
          {spend ? (isClear(view) ? `You’d still be covered all month.` : a.title.replace('You’re', 'You’d be')) : a.title}
        </Text>
        <T tone="dim" style={s.detail}>{a.detail}</T>

        <BalanceChart f={f} spend={spend} ghost={ghost} focusIndex={focusIndex !== null && focusIndex >= 0 ? focusIndex : null}
          onScrub={setScrub} />

        <WhatIf spend={spend} onChange={setSpend} />
        <Fix f={f} onProposal={setGhost} />
      </View>
    </Reveal3D>
  );
  const coming = (
    <Reveal3D order={1} scrollY={scrollY} viewport={viewport}>
      <ComingUp f={f} selectedDate={point && day ? point.date : null} onFocusDate={setRowDate} />
    </Reveal3D>
  );

  return wide ? (
    <View style={s.wideRow}>
      <View style={{ flex: 1.45 }}>{hero}</View>
      <View style={{ flex: 1 }}>{coming}</View>
    </View>
  ) : (
    <View style={{ gap: 16 }}>{hero}{coming}</View>
  );
}

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

function BalanceChart({ f, spend, ghost, focusIndex, onScrub }: {
  f: Forecast; spend: number; ghost: number | null; focusIndex: number | null; onScrub: (i: number | null) => void;
}) {
  const reduced = useReducedMotion();
  const [w, setW] = useState(0);
  const n = f.points.length;
  const base = useMemo(() => f.points.map((p) => p.balance), [f.points]);

  // A fixed scale that leaves room for every preview, so moving the line never rescales the chart.
  const top = Math.max(...base, f.safe_floor) + Math.max(0, f.safe_floor - f.low.balance) + 60;
  const bottom = Math.min(...base, f.safe_floor) - Math.max(...WHAT_IFS);
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
    return { cx: cx.get(), cy: yIn(v), opacity: cOn.get(), fill: v < f.safe_floor ? C.red : '#fff' };
  });

  const lowI = f.points.findIndex((p) => p.date === f.low.date);
  const dipping = f.low.balance - spend < f.safe_floor;
  const pays = f.events.filter((e) => e.kind === 'paycheck').map((e) => f.points.findIndex((p) => p.date === e.date)).filter((i) => i > 0);
  const anchor = lowI > n * 0.75 ? 'end' : lowI < n * 0.25 ? 'start' : 'middle';

  // pointer handlers: press-down starts tracking at once (no movement threshold needed on a chart)
  const touch = {
    onStartShouldSetResponder: () => true,
    onMoveShouldSetResponder: () => true,
    onResponderTerminationRequest: () => false, // keep the finger until it lifts
    onResponderGrant: (e: GestureResponderEvent) => { scrubbing.current = true; at(e.nativeEvent.locationX); },
    onResponderMove: (e: GestureResponderEvent) => at(e.nativeEvent.locationX),
    onResponderRelease: end,
    onResponderTerminate: end,
  };
  const hover = Platform.OS === 'web'
    ? {
      onPointerMove: (e: { nativeEvent: { offsetX?: number; pointerType?: string } }) => {
        if (e.nativeEvent.pointerType === 'mouse' && e.nativeEvent.offsetX !== undefined) at(e.nativeEvent.offsetX);
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
                <Stop offset="0" stopColor="#ffffff" stopOpacity={0.14} />
                <Stop offset="1" stopColor="#ffffff" stopOpacity={0} />
              </LinearGradient>
              <ClipPath id="above"><Rect x={0} y={0} width={w} height={floorY} /></ClipPath>
              <ClipPath id="below"><Rect x={0} y={floorY} width={w} height={CH - floorY} /></ClipPath>
            </Defs>
            <G clipPath="url(#above)"><AnimatedPath fill="url(#fillUp)" animatedProps={toAxis} /></G>
            <G clipPath="url(#below)"><AnimatedPath fill={C.red} fillOpacity={0.4} animatedProps={toFloor} /></G>
            <Line x1={0} x2={w} y1={floorY} y2={floorY} stroke={C.text3} strokeWidth={1} strokeDasharray="4 5" />
            <SvgText x={w - 4} y={floorY - 7} fill={C.text2} fontSize={12} fontFamily={F.body} textAnchor="end">
              {`${money(f.safe_floor, 0)} you keep`}
            </SvgText>
            {ghostD ? (
              <AnimatedPath d={ghostD} fill="none" stroke={C.green} strokeWidth={2} strokeDasharray="6 6" strokeLinecap="round" animatedProps={ghostProps} />
            ) : null}
            <G clipPath="url(#above)"><AnimatedPath fill="none" stroke="#fff" strokeWidth={2.5} strokeLinejoin="round" animatedProps={lineProps} /></G>
            <G clipPath="url(#below)"><AnimatedPath fill="none" stroke={C.red} strokeWidth={2.5} strokeLinejoin="round" animatedProps={lineProps} /></G>
            {pays.map((i) => (
              <RidingDot key={i} i={i} x={xOf(i)} from={from} to={to} morph={morph} offset={offset} yIn={yIn} />
            ))}
            <AnimatedCircle cx={xOf(0)} r={5} fill="#fff" animatedProps={todayDot} />
            {lowI >= 0 && dipping && (
              <RidingLabel i={lowI} x={xOf(lowI)} from={from} to={to} morph={morph} offset={offset} yIn={yIn} anchor={anchor}
                text={`${money(f.low.balance - spend, 0)} on ${monthDay(f.low.date)}`} />
            )}
            <AnimatedLine y1={PAD.top - 8} y2={CH - PAD.bottom} stroke="#fff" strokeOpacity={0.5} strokeWidth={1} animatedProps={cursorLine} />
            <AnimatedCircle r={6} stroke={C.card} strokeWidth={2.5} animatedProps={cursorDot} />
          </Svg>
        )}
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
      <T tone="faint" style={s.hint}>{Platform.OS === 'web' ? 'Point at the line to see any day.' : 'Drag along the line to see any day.'}</T>
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
    <AnimatedSvgText x={x} fill={C.red} fontSize={13} fontFamily={F.bodySemi} textAnchor={anchor} animatedProps={props}>
      {text}
    </AnimatedSvgText>
  );
}

/* ---------------- what if ---------------- */

/** "What if I spend …today?" — tap an amount to see it on the line; tap again to clear. */
function WhatIf({ spend, onChange }: { spend: number; onChange: (n: number) => void }) {
  return (
    <View style={s.whatIf}>
      <T style={s.whatIfLabel}>What if I spend today:</T>
      <View style={s.chips}>
        {WHAT_IFS.map((n) => (
          <Chip key={n} on={spend === n} label={money(n, 0)} onPress={() => onChange(spend === n ? 0 : n)} />
        ))}
      </View>
    </View>
  );
}

function Chip({ on, label, onPress }: { on: boolean; label: string; onPress: () => void }) {
  const reduced = useReducedMotion();
  const press = useSharedValue(0);
  const anim = useAnimatedStyle(() => ({ transform: [{ scale: 1 - 0.06 * press.get() }] }));
  return (
    <Pressable onPress={onPress} accessibilityRole="button" accessibilityState={{ selected: on }}
      accessibilityLabel={`What if I spend ${label} today`}
      onPressIn={() => !reduced && press.set(withTiming(1, { duration: 80 }))} // feedback on press-down
      onPressOut={() => press.set(reduced ? 0 : withSpring(0, { dampingRatio: 0.7, duration: 350 }))}>
      <Animated.View style={[s.chip, on && s.chipOn, anim]}>
        <Text style={[s.chipText, on && s.chipTextOn]}>{label}</Text>
      </Animated.View>
    </Pressable>
  );
}

/* ---------------- 3D ---------------- */

/**
 * A card that tilts up into place in 3D: on load (staggered by `order`) and, on phones, as it's
 * scrolled into view — rotated back on the X axis, a little lower and smaller, until it's flat.
 * `lift` gives the card a small 3D lift when it becomes true (the dip got covered).
 */
function Reveal3D({ order, scrollY, viewport, lift, children }: PropsWithChildren<{
  order: number; scrollY?: SharedValue<number>; viewport?: number; lift?: boolean;
}>) {
  const reduced = useReducedMotion();
  const enter = useSharedValue(reduced ? 1 : 0);
  const yTop = useSharedValue(0);
  const pop = useSharedValue(0);
  useEffect(() => {
    if (!reduced) enter.set(withDelay(80 + order * 140, withSpring(1, { dampingRatio: 1, duration: 900 })));
  }, [reduced, order, enter]);
  const wasLifted = useRef(lift);
  useEffect(() => {
    if (lift && !wasLifted.current && !reduced) pop.set(withSequence(withSpring(1, LIFT), withSpring(0, { dampingRatio: 1, duration: 700 })));
    wasLifted.current = lift;
  }, [lift, reduced, pop]);

  const style = useAnimatedStyle(() => {
    if (reduced) return {};
    // how far into the viewport the card's top edge has come (0 = just below the fold, 1 = well in)
    const seen = scrollY && viewport ? Math.min(1, Math.max(0, (viewport + scrollY.get() - yTop.get()) / 260)) : 1;
    const p = Math.min(enter.get(), seen);
    return {
      opacity: 0.25 + 0.75 * p,
      transform: [
        { perspective: 1000 },
        { translateY: (1 - p) * 36 - pop.get() * 6 },
        { rotateX: `${(1 - p) * 18 - pop.get() * 4}deg` },
        { scale: 0.95 + 0.05 * p + pop.get() * 0.015 },
      ],
    };
  });
  return (
    <Animated.View onLayout={(e: LayoutChangeEvent) => yTop.set(e.nativeEvent.layout.y)} style={[style, { transformOrigin: 'center top' }]}>
      {children}
    </Animated.View>
  );
}

const s = StyleSheet.create({
  wideRow: { flexDirection: 'row', gap: 24, alignItems: 'flex-start' },
  hero: { backgroundColor: C.card, borderRadius: RADIUS + 4, padding: 24 },
  kicker: { fontSize: 15 },
  balance: { fontFamily: F.condBold, fontSize: 64, lineHeight: 66, color: C.text, letterSpacing: -1, marginTop: 2 },
  dayLine: { fontSize: 15, minHeight: 20 },
  title: { fontFamily: F.bodySemi, fontSize: 26, lineHeight: 32, color: C.text, marginTop: 10 },
  detail: { fontSize: 17, lineHeight: 25, marginTop: 6, maxWidth: 600 },

  axis: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginTop: 2 },
  axisText: { fontSize: 13 },
  legend: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  legendDot: { width: 9, height: 9, borderRadius: 5 },
  legendDash: { width: 16, height: 0, borderTopWidth: 2, borderStyle: 'dashed', borderColor: C.green, marginLeft: 10 },
  hint: { fontSize: 13, marginTop: 6 },

  whatIf: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 12, marginTop: 18 },
  whatIfLabel: { fontSize: 16 },
  chips: { flexDirection: 'row', gap: 8 },
  chip: { height: 38, paddingHorizontal: 16, borderRadius: 19, borderWidth: 1, borderColor: C.line, backgroundColor: C.card2, alignItems: 'center', justifyContent: 'center' },
  chipOn: { backgroundColor: '#fff', borderColor: '#fff' },
  chipText: { fontFamily: F.bodySemi, fontSize: 15, color: C.text },
  chipTextOn: { color: '#111' },
});

/**
 * Two candidate Today layouts, built to be compared side by side (open the site with ?v=compare,
 * or ?v=a / ?v=b for one at a time). Both say the same thing in the same plain words; only the
 * picture differs:
 *  - A: the balance line — 30 days of checking as one smooth line, red where it dips under the
 *       amount you keep; everyone reads "line going down into the red".
 *  - B: the runway, simplified — the plane at today, a runway as long as you're covered, one red
 *       end marker; the takeoff plays after an approved fix.
 * Shared: one sentence that answers "am I okay?", a fix button that says what it does, and a
 * plain "Coming up" list with payday and spare money. Sentence case everywhere, 16px+ body text.
 */
import { useEffect, useState } from 'react';
import { type LayoutChangeEvent, Pressable, StyleSheet, Text, View } from 'react-native';
import Animated, { Easing, useAnimatedProps, useReducedMotion, useSharedValue, withTiming } from 'react-native-reanimated';
import Svg, { Circle, ClipPath, Defs, G, Line, LinearGradient, Path, Rect, Stop, Text as SvgText } from 'react-native-svg';

import { ApprovalCard } from '@/components/rw/approval-card';
import { RunwayStrip } from '@/components/rw/runway-strip';
import { PressableScale, T } from '@/components/rw/ui';
import { C, F, RADIUS, SYSTEM_FONT } from '@/constants/runway';
import { api } from '@/lib/api';
import { fromIso, money, monthDay, weekdayDate } from '@/lib/format';
import { isClear, nextPaycheck, runwayDays, safeToSpend, upcoming } from '@/lib/runway';
import type { Forecast, PendingAction } from '@/lib/types';

/** "Sunday, Nov 2" */
const longDate = (iso: string) => fromIso(iso).toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric' });

/** The answer to "am I okay?", in two plain sentences — the same words in both options. */
export function answer(f: Forecast) {
  if (isClear(f)) {
    return { title: 'You’re covered all month.', detail: `Your balance stays above the ${money(f.safe_floor, 0)} you like to keep.` };
  }
  const dip = f.points[runwayDays(f)];
  return {
    title: `You’re fine until ${longDate(dip.date)}.`,
    detail: `Then your balance drops to ${money(f.low.balance, 0)} on ${monthDay(f.low.date)}, below the ${money(f.safe_floor, 0)} you like to keep.`,
  };
}

/* ---------------- option A: the balance line ---------------- */

export function OptionA({ f, compact }: { f: Forecast; compact?: boolean }) {
  const a = answer(f);
  return (
    <View style={s.stack}>
      <View style={s.hero}>
        <T tone="dim" style={s.kicker}>In checking today</T>
        <Text style={[s.balance, compact && { fontSize: 52, lineHeight: 54 }]}>{money(f.points[0].balance, 0)}</Text>
        <Text style={[s.title, compact && s.titleCompact]}>{a.title}</Text>
        <T tone="dim" style={s.detail}>{a.detail}</T>
        <BalanceLine f={f} />
        <Fix f={f} />
      </View>
      <ComingUp f={f} />
    </View>
  );
}

const CH = 200; // chart height
const PAD = { top: 26, bottom: 26, left: 6, right: 6 };
const EASE_OUT = Easing.bezier(0.23, 1, 0.32, 1);
const AnimatedPath = Animated.createAnimatedComponent(Path);

/**
 * 30 days of checking as one line: white above the amount you keep, red (and red-shaded) where it
 * goes under. Straight segments, because bills and pay land on a day — a curve would invent dips.
 * On open the line draws itself left to right and the shading fades in behind it, once.
 */
function BalanceLine({ f }: { f: Forecast }) {
  const reduced = useReducedMotion();
  const [w, setW] = useState(0);
  const draw = useSharedValue(reduced ? 1 : 0);
  useEffect(() => {
    if (w > 0 && !reduced) draw.set(withTiming(1, { duration: 1200, easing: EASE_OUT }));
  }, [w, reduced, draw]);

  const pts = f.points;
  const vals = pts.map((p) => p.balance);
  const top = Math.max(...vals, f.safe_floor), bottom = Math.min(...vals, f.safe_floor);
  const lo = bottom - (top - bottom) * 0.12, span = Math.max(top - lo, 1); // room under the low point
  const x = (i: number) => PAD.left + (i / (pts.length - 1)) * (w - PAD.left - PAD.right);
  const y = (v: number) => PAD.top + (1 - (v - lo) / span) * (CH - PAD.top - PAD.bottom);
  const floorY = y(f.safe_floor);
  const xy = pts.map((p, i) => [x(i), y(p.balance)]);
  const line = xy.map(([a, b], i) => `${i ? 'L' : 'M'}${a},${b}`).join(' ');
  const length = xy.reduce((n, [a, b], i) => (i ? n + Math.hypot(a - xy[i - 1][0], b - xy[i - 1][1]) : 0), 0);
  const last = xy[xy.length - 1][0], first = xy[0][0];
  const toBase = `${line} L${last},${CH - PAD.bottom} L${first},${CH - PAD.bottom} Z`; // line down to the axis
  const toFloor = `${line} L${last},${floorY} L${first},${floorY} Z`; // between the line and the floor
  const lowI = pts.findIndex((p) => p.date === f.low.date);
  const dipping = f.low.balance < f.safe_floor;
  const pays = f.events.filter((e) => e.kind === 'paycheck').map((e) => pts.findIndex((p) => p.date === e.date)).filter((i) => i > 0);
  const lowAnchor = lowI > pts.length * 0.75 ? 'end' : lowI < pts.length * 0.25 ? 'start' : 'middle';

  const lineProps = useAnimatedProps(() => ({ strokeDashoffset: length * (1 - draw.get()) }));
  const fillProps = useAnimatedProps(() => ({ opacity: Math.max(0, (draw.get() - 0.35) / 0.65) }));

  return (
    <View style={{ marginTop: 10 }}>
      <View onLayout={(e: LayoutChangeEvent) => setW(e.nativeEvent.layout.width)} style={{ height: CH }}
        accessible accessibilityRole="image"
        accessibilityLabel={`Your balance over the next 30 days. Lowest ${money(f.low.balance, 0)} on ${weekdayDate(f.low.date)}.`}>
        {w > 0 && (
          <Svg width={w} height={CH}>
            <Defs>
              <LinearGradient id="fillUp" x1="0" y1="0" x2="0" y2="1">
                <Stop offset="0" stopColor={C.text} stopOpacity={0.14} />
                <Stop offset="1" stopColor={C.text} stopOpacity={0} />
              </LinearGradient>
              <ClipPath id="above"><Rect x={0} y={0} width={w} height={floorY} /></ClipPath>
              <ClipPath id="below"><Rect x={0} y={floorY} width={w} height={CH - floorY} /></ClipPath>
            </Defs>
            <AnimatedPath d={toBase} fill="url(#fillUp)" clipPath="url(#above)" animatedProps={fillProps} />
            <AnimatedPath d={toFloor} fill={C.red} fillOpacity={0.4} clipPath="url(#below)" animatedProps={fillProps} />
            {/* the amount you keep */}
            <Line x1={0} x2={w} y1={floorY} y2={floorY} stroke={C.text3} strokeWidth={1} strokeDasharray="4 5" />
            <SvgText x={w - 2} y={floorY - 7} fill={C.text2} fontSize={12} fontFamily={F.body} textAnchor="end">
              {`${money(f.safe_floor, 0)} you keep`}
            </SvgText>
            {/* the balance: white above the line you keep, red below it */}
            <G clipPath="url(#above)">
              <AnimatedPath d={line} fill="none" stroke={C.text} strokeWidth={2.5} strokeLinejoin="round" strokeLinecap="round"
                strokeDasharray={`${length} ${length}`} animatedProps={lineProps} />
            </G>
            <G clipPath="url(#below)">
              <AnimatedPath d={line} fill="none" stroke={C.red} strokeWidth={2.5} strokeLinejoin="round" strokeLinecap="round"
                strokeDasharray={`${length} ${length}`} animatedProps={lineProps} />
            </G>
            {pays.map((i) => <Circle key={i} cx={xy[i][0]} cy={xy[i][1]} r={4.5} fill={C.green} />)}
            <Circle cx={xy[0][0]} cy={xy[0][1]} r={5} fill={C.text} />
            {lowI >= 0 && dipping && (
              <G>
                <Circle cx={xy[lowI][0]} cy={xy[lowI][1]} r={5.5} fill={C.red} stroke={C.card} strokeWidth={2} />
                <SvgText x={xy[lowI][0]} y={xy[lowI][1] + 21} fill={C.red} fontSize={13} fontFamily={F.bodySemi} textAnchor={lowAnchor}>
                  {`${money(f.low.balance, 0)} on ${monthDay(f.low.date)}`}
                </SvgText>
              </G>
            )}
          </Svg>
        )}
      </View>
      <View style={s.axis}>
        <T tone="dim" style={s.axisText}>Today</T>
        <View style={s.legend}>
          <View style={[s.legendDot, { backgroundColor: C.green }]} />
          <T tone="dim" style={s.axisText}>Payday</T>
        </View>
        <T tone="dim" style={s.axisText}>{monthDay(pts[pts.length - 1].date)}</T>
      </View>
    </View>
  );
}

/* ---------------- option B: the runway, simplified ---------------- */

export function OptionB({ f, takeoffKey, compact }: { f: Forecast; takeoffKey: number; compact?: boolean }) {
  const a = answer(f);
  const days = runwayDays(f), horizon = f.points.length - 1;
  return (
    <View style={s.stack}>
      <View style={s.hero}>
        <Text style={[s.title, s.titleB, compact && s.titleCompact]}>{a.title}</Text>
        <T tone="dim" style={s.detail}>{a.detail}</T>
        <View style={{ marginTop: 6 }}>
          <RunwayStrip minimal days={days} horizon={horizon} endLabel={days < horizon ? monthDay(f.points[days].date) : ''}
            lastLabel={monthDay(f.points[horizon].date)} takeoffKey={takeoffKey} />
        </View>
        <T tone="dim" style={s.caption}>
          {isClear(f) ? 'The runway reaches the end of the month.' : `The runway is how long your money lasts: ${days} of the next ${horizon} days.`}
        </T>
        <Fix f={f} />
      </View>
      <ComingUp f={f} />
    </View>
  );
}

/* ---------------- shared ---------------- */

/**
 * The fix: asks the agent for a proposal, then the person approves it here. Says what it does.
 * `onProposal` reports the proposed amount (so the chart can preview the result) and null when it's gone.
 */
export function Fix({ f, onProposal }: { f: Forecast; onProposal?: (amount: number | null) => void }) {
  const [proposal, setProposal] = useState<PendingAction | null>(null);
  const [asking, setAsking] = useState(false);
  const [failed, setFailed] = useState(false);
  if (isClear(f)) return null;

  async function getFix() {
    setAsking(true);
    setFailed(false);
    try {
      const r = await api.chat('Fix it');
      setProposal(r.pending_action);
      onProposal?.(r.pending_action?.amount ?? null);
      if (!r.pending_action) setFailed(true);
    } catch {
      setFailed(true);
    } finally {
      setAsking(false);
    }
  }

  if (proposal) return <View style={{ marginTop: 16 }}><ApprovalCard action={proposal} compact onDone={() => onProposal?.(null)} /></View>;
  return (
    <View style={s.fix}>
      <PressableScale onPress={getFix} disabled={asking} accessibilityRole="button" style={[s.fixBtn, asking && { opacity: 0.6 }]}>
        <Text style={s.fixText}>{asking ? 'Finding a fix…' : 'Cover this dip'}</Text>
      </PressableScale>
      <T tone="dim" style={s.fixNote}>
        {failed ? 'Couldn’t find a fix. Try again, or ask in the chat.' : 'We’ll suggest moving money from savings. Nothing moves until you say yes.'}
      </T>
    </View>
  );
}

/**
 * Bills and pay in the next two weeks, then payday and spare money in plain words.
 * With `onFocusDate`, rows are interactive: hover or press a row to point at that day on the chart;
 * the row for `selectedDate` (from scrubbing the chart) lights up, so the two stay in step.
 */
export function ComingUp({ f, selectedDate, onFocusDate, bare }: {
  f: Forecast; selectedDate?: string | null; onFocusDate?: (date: string | null) => void;
  /** no card of its own (the caller wraps it) */
  bare?: boolean;
}) {
  const items = upcoming(f);
  const pay = nextPaycheck(f);
  const spare = safeToSpend(f);
  return (
    <View style={!bare && s.card}>
      <Text style={s.cardTitle}>Coming up</Text>
      <View style={{ marginTop: 6 }}>
        {items.length === 0 && <T tone="dim" style={s.row}>Nothing due in the next two weeks.</T>}
        {items.map((e, i) => (
          <Pressable key={`${e.date}-${e.label}-${i}`} disabled={!onFocusDate}
            accessibilityRole={onFocusDate ? 'button' : undefined}
            accessibilityLabel={`${weekdayDate(e.date)}, ${e.label}, ${e.amount > 0 ? 'plus' : 'minus'} ${money(Math.abs(e.amount), 0)}. Show on the chart.`}
            onHoverIn={() => onFocusDate?.(e.date)} onHoverOut={() => onFocusDate?.(null)}
            onPressIn={() => onFocusDate?.(e.date)}
            style={({ pressed }) => [s.row, i > 0 && s.rowLine, (pressed || selectedDate === e.date) && s.rowOn]}>
            <T tone="dim" style={s.rowDate}>{weekdayDate(e.date)}</T>
            <T style={s.rowName} numberOfLines={1}>{e.label}</T>
            <Text style={[s.rowAmount, { color: e.amount > 0 ? C.green : C.text }]}>
              {`${e.amount > 0 ? '+' : '−'}${money(Math.abs(e.amount), 0)}`}
            </Text>
          </Pressable>
        ))}
      </View>
      {/* framed by the caller, payday and spare money already show as tiles */}
      {!bare && <View style={s.facts}>
        <View style={s.fact}>
          <T tone="dim" style={s.factLabel}>Next payday</T>
          <T style={s.factValue}>{pay ? `${money(pay.amount, 0)} on ${weekdayDate(pay.date)}` : 'None in the next month'}</T>
        </View>
        <View style={s.fact}>
          <T tone="dim" style={s.factLabel}>Spare money today</T>
          <T style={s.factValue}>{spare > 0 ? `${money(spare, 0)} you can spend` : pay ? `None. Wait for ${fromIso(pay.date).toLocaleDateString('en-US', { weekday: 'long' })}’s pay.` : 'None right now.'}</T>
        </View>
      </View>}
    </View>
  );
}

const s = StyleSheet.create({
  stack: { gap: 16 },
  hero: { backgroundColor: C.card, borderRadius: RADIUS + 4, padding: 22 },
  kicker: { fontSize: 15 },
  balance: { fontFamily: F.condBold, fontSize: 64, lineHeight: 66, color: C.text, letterSpacing: -1, marginTop: 2 },
  title: { fontFamily: F.bodySemi, fontSize: 26, lineHeight: 32, color: C.text, marginTop: 14 },
  titleB: { fontSize: 32, lineHeight: 38, marginTop: 0 },
  titleCompact: { fontSize: 24, lineHeight: 30 },
  detail: { fontSize: 17, lineHeight: 25, marginTop: 6, maxWidth: 560 },
  caption: { fontSize: 15, lineHeight: 21, marginTop: 2 },
  axis: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginTop: 2 },
  axisText: { fontSize: 13 },
  legend: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  legendDot: { width: 9, height: 9, borderRadius: 5 },

  fix: { marginTop: 18, gap: 10 },
  fixBtn: { alignSelf: 'flex-start', height: 50, paddingHorizontal: 26, borderRadius: 25, backgroundColor: C.primary, alignItems: 'center', justifyContent: 'center' },
  fixText: { fontFamily: F.bodySemi, fontSize: 17, color: C.onPrimary },
  fixNote: { fontSize: 15, lineHeight: 21 },

  card: { backgroundColor: C.card, borderRadius: RADIUS + 4, padding: 22 },
  cardTitle: { fontFamily: SYSTEM_FONT, fontWeight: '600', fontSize: 19, color: C.text },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 12 },
  rowLine: { borderTopWidth: 1, borderTopColor: C.line },
  // lit when the row's day is selected on the chart (or pressed); the bleed keeps text aligned
  rowOn: { backgroundColor: C.card2, marginHorizontal: -10, paddingHorizontal: 10, borderRadius: 10, borderTopColor: 'transparent' },
  rowDate: { width: 104, fontSize: 15, fontFamily: SYSTEM_FONT },
  rowName: { flex: 1, fontSize: 16, fontFamily: SYSTEM_FONT },
  rowAmount: { fontFamily: SYSTEM_FONT, fontWeight: '600', fontSize: 16, fontVariant: ['tabular-nums'] },
  facts: { marginTop: 10, paddingTop: 14, borderTopWidth: 1, borderTopColor: C.line, gap: 12 },
  fact: { gap: 2 },
  factLabel: { fontSize: 14, fontFamily: SYSTEM_FONT },
  factValue: { fontSize: 16, fontFamily: SYSTEM_FONT },
});

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
import { type GestureResponderEvent, type LayoutChangeEvent, Platform, Pressable, type StyleProp, StyleSheet, Text, View, type ViewStyle } from 'react-native';
import Animated, {
  Easing,
  interpolateColor,
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
import Svg, { Circle, ClipPath, Defs, G, Line, LinearGradient, Path, RadialGradient, Rect, Stop, Text as SvgText } from 'react-native-svg';

import { answer, ComingUp, Fix } from '@/components/today/today-options';
import { T } from '@/components/rw/ui';
import { C, F, RADIUS, SYSTEM_FONT } from '@/constants/runway';
import { useLoad } from '@/hooks/use-load';
import { api } from '@/lib/api';
import { fromIso, money, monthDay, weekdayDate } from '@/lib/format';
import { isClear, nextPaycheck, runwayDays, safeToSpend } from '@/lib/runway';
import { useSession } from '@/lib/session';
import type { BridgeStatus, Forecast, SafetyLimit, SafetyNetSummary } from '@/lib/types';

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

export function TodayInteractive({ f, name, wide, scrollY, viewport, onMoneyMoved }: {
  f: Forecast; name?: string; wide: boolean; scrollY?: SharedValue<number>; viewport?: number;
  /** real money moved (a bridge, a repayment, a demo reset): re-fetch the forecast */
  onMoneyMoved?: () => void;
}) {
  const [spend, setSpend] = useState(0); // what-if amount, 0 = off
  const [ghost, setGhost] = useState<number | null>(null); // a proposed fix, previewed on the chart
  const [scrub, setScrub] = useState<number | null>(null); // day index under the finger/pointer
  const [rowDate, setRowDate] = useState<string | null>(null); // day pointed at from Coming up
  const family = useLoad(() => api.safetyNet());

  const view = shifted(f, -spend);
  const a = answer(view);
  const focusIndex = rowDate ? f.points.findIndex((p) => p.date === rowDate) : null;
  const day = scrub ?? (focusIndex !== null && focusIndex >= 0 ? focusIndex : null);
  const point = day ? view.points[day] : null; // day 0 is today: the default view
  const dayEvents = point ? f.events.filter((e) => e.date === point.date && e.kind !== 'spending') : [];
  const covered = isClear(view);
  const dip = covered ? null : view.points[runwayDays(view)];
  const pay = nextPaycheck(f);
  const spare = safeToSpend(view);
  const lowBad = view.low.balance < view.safe_floor;

  const hero = (
    <Reveal3D order={0} scrollY={scrollY} viewport={viewport} lift={isClear(f)}>
      <View style={s.hero}>
        <Text style={s.hello}>{`Hi ${name ?? 'there'}`}</Text>
        <Text style={s.date}>{longDay(f.points[0].date)}</Text>
        {/* the number follows the cursor: today's balance, or the scrubbed day's */}
        <Text style={s.balLabel} accessibilityLiveRegion="polite">
          {point ? weekdayDate(point.date) : spend ? `If you spend ${money(spend, 0)} today` : 'In checking'}
        </Text>
        <Text style={[s.bal, point && point.balance < f.safe_floor && { color: C.red }]}>
          {money(point ? point.balance : view.points[0].balance, 0)}
        </Text>
        <Text style={s.subline}>
          {point
            ? dayEvents.length
              ? dayEvents.map((e) => `${e.label} ${e.amount > 0 ? '+' : '−'}${money(Math.abs(e.amount), 0)}`).join(' · ')
              : 'Everyday spending only'
            : ' '}
        </Text>
        <Pill tone={covered ? 'good' : 'bad'} text={covered ? (spend ? 'Still covered all month' : 'Covered all month') : `Dips on ${monthDay(dip!.date)}`} />
      </View>
    </Reveal3D>
  );

  const tiles = (
    <Reveal3D order={1} scrollY={scrollY} viewport={viewport}>
      <View style={s.tiles}>
        <Tile label="Next payday" value={pay ? money(pay.amount, 0) : 'None'} sub={pay ? weekdayDate(pay.date) : 'in the next month'} />
        <Tile label="Spare money today" value={money(spare, 0)} sub={spare > 0 ? 'after bills' : 'wait for payday'} />
        <Tile label="Lowest point" value={money(view.low.balance, 0)} sub={monthDay(view.low.date)} tone={lowBad ? 'bad' : undefined} />
      </View>
    </Reveal3D>
  );

  const chart = (
    <Reveal3D order={2} scrollY={scrollY} viewport={viewport}>
      <Glass>
        <Text style={s.cardTitle}>Next 30 days</Text>
        <BalanceChart f={f} spend={spend} ghost={ghost} focusIndex={focusIndex !== null && focusIndex >= 0 ? focusIndex : null}
          onScrub={setScrub} />
        <WhatIf spend={spend} onChange={setSpend} />
        <Fix f={f} onProposal={setGhost} />
      </Glass>
    </Reveal3D>
  );

  const moved = () => {
    family.reload();
    onMoneyMoved?.();
  };
  // the answer in a sentence, then the family safety net from this person's side
  const notes = (
    <Reveal3D order={3} scrollY={scrollY} viewport={viewport}>
      <View style={{ gap: 10 }}>
        <Callout tone={covered ? 'good' : 'bad'} title={spend ? a.title.replace('You’re', 'You’d be') : a.title} text={a.detail}>
          {!covered && !spend && family.data && family.data.limits_for_me.some((l) => l.enabled && l.remaining > 0)
            && !family.data.borrowed.some((b) => OUT.includes(b.status) || b.status === 'pending_approval') ? (
              <AskFamily onDone={moved} />
            ) : null}
        </Callout>
        {family.data ? <Family sum={family.data} onMoved={moved} /> : null}
      </View>
    </Reveal3D>
  );

  const coming = (
    <Reveal3D order={4} scrollY={scrollY} viewport={viewport}>
      <Glass>
        <ComingUp bare f={f} selectedDate={point ? point.date : null} onFocusDate={setRowDate} />
      </Glass>
    </Reveal3D>
  );

  return (
    <View style={{ gap: 18 }}>
      {hero}
      {tiles}
      {wide ? (
        <View style={s.wideRow}>
          <View style={{ flex: 1.45 }}>{chart}</View>
          <View style={{ flex: 1, gap: 18 }}>{notes}{coming}</View>
        </View>
      ) : (
        <>{notes}{chart}{coming}</>
      )}
      <DemoReset onDone={moved} />
    </View>
  );
}

/* ---------------- family safety net ---------------- */

const OUT: BridgeStatus[] = ['active', 'repay_failed']; // money is with the borrower
const DEMO = ['maya', 'jordan', 'sam'];

/** A small two-step action: the first tap asks, the second does it. Feedback on press-down. */
function ActionButton({ label, confirm, onPress, tone = 'light' }: {
  label: string; confirm?: string; onPress: () => Promise<void>; tone?: 'light' | 'ghost';
}) {
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    if (confirm && !asking) return setAsking(true);
    setBusy(true);
    try {
      await onPress();
    } finally {
      setBusy(false);
      setAsking(false);
    }
  };
  return (
    <View style={s.actionRow}>
      <Pressable onPress={run} disabled={busy} accessibilityRole="button"
        style={({ pressed }) => [s.action, tone === 'ghost' && s.actionGhost, (pressed || busy) && { opacity: 0.7, transform: [{ scale: 0.97 }] }]}>
        <Text style={[s.actionText, tone === 'ghost' && { color: C.text }]}>{busy ? 'One moment…' : asking ? confirm : label}</Text>
      </Pressable>
      {asking && !busy ? <Pressable onPress={() => setAsking(false)} accessibilityRole="button"><Text style={s.cancel}>Cancel</Text></Pressable> : null}
    </View>
  );
}

/** Errors from a money action, in the server's own plain words (409s explain why). */
function useNote() {
  const [note, setNote] = useState<string | null>(null);
  const guard = (fn: () => Promise<unknown>) => async () => {
    setNote(null);
    try {
      await fn();
    } catch (e) {
      const m = e instanceof Error ? e.message : '';
      setNote(m.match(/"detail":"([^"]+)"/)?.[1] ?? 'That didn’t go through. Please try again.');
    }
  };
  return { note, guard };
}

/** "Ask family to cover it": runs the safety net now — it covers the dip within a lender's limit, or asks them. */
function AskFamily({ onDone }: { onDone: () => void }) {
  const { note, guard } = useNote();
  return (
    <View style={{ marginTop: 10 }}>
      <ActionButton label="Ask family to cover it" onPress={guard(async () => {
        await api.runSafetyNet();
        onDone();
      })} />
      {note ? <Text style={s.noteText}>{note}</Text> : null}
    </View>
  );
}

/** Everything the safety net is doing for this person, from their side. */
function Family({ sum, onMoved }: { sum: SafetyNetSummary; onMoved: () => void }) {
  const { note, guard } = useNote();
  const borrowed = sum.borrowed.filter((b) => OUT.includes(b.status));
  const waitingOnOthers = sum.borrowed.filter((b) => b.status === 'pending_approval');
  const lent = sum.lent.filter((b) => OUT.includes(b.status));
  const shownIds = new Set([...borrowed, ...lent, ...sum.approvals_waiting, ...waitingOnOthers].map((b) => b.id));
  const news = sum.events.filter((e) => !e.bridge_id || !shownIds.has(e.bridge_id)).slice(0, 2);
  return (
    <>
      {borrowed.map((b) => (
        <Callout key={b.id} tone="info" title={`${b.lender_name} has your back`}
          text={`${b.lender_name} covered ${money(b.amount, 0)} before ${monthDay(b.shortfall_date)}. It goes back automatically on payday, ${weekdayDate(b.due_date)}.`}>
          <View style={{ marginTop: 10 }}>
            <ActionButton label={`Pay ${b.lender_name} back now`} confirm={`Pay ${money(b.amount, 0)} back now?`}
              onPress={guard(async () => {
                await api.repayBridge(b.id);
                onMoved();
              })} />
          </View>
        </Callout>
      ))}
      {waitingOnOthers.map((b) => (
        <Callout key={b.id} tone="warn" title={`Asked ${b.lender_name}`}
          text={`${money(b.amount, 0)} is over ${b.lender_name}’s limit, so they’re approving it. You’ll see it here the moment they do.`} />
      ))}
      {sum.approvals_waiting.map((b) => (
        <Callout key={b.id} tone="warn" title={`${b.borrower_name} needs ${money(b.amount, 0)}`} text={b.reason}>
          {b.approval_channel === 'auth0_push' ? (
            <Text style={s.noteText}>Approve it on your phone — Auth0 sent you a request.</Text>
          ) : (
            <View style={s.twoActions}>
              <ActionButton label="Approve" onPress={guard(async () => {
                await api.approveBridge(b.id);
                onMoved();
              })} />
              <ActionButton label="Decline" tone="ghost" onPress={guard(async () => {
                await api.declineBridge(b.id);
                onMoved();
              })} />
            </View>
          )}
        </Callout>
      ))}
      {lent.map((b) => (
        <Callout key={b.id} tone="info" title={`${b.borrower_name} has ${money(b.amount, 0)} of yours`}
          text={`It comes back automatically on ${weekdayDate(b.due_date)}. Your own balance stays above what you keep.`} />
      ))}
      {sum.limits_i_set.map((l) => (
        <LimitChips key={`${l.lender}-${l.borrower}`} limit={l} onSet={guard(async () => onMoved())} />
      ))}
      {news.map((e) => <Callout key={`${e.at}-${e.kind}`} tone="info" title="From your family" text={e.message} />)}
      {note ? <Text style={s.noteText}>{note}</Text> : null}
    </>
  );
}

const LIMITS = [0, 50, 100, 200];

/** The lender sets how much they'll cover automatically — the person whose money it is decides. */
function LimitChips({ limit, onSet }: { limit: SafetyLimit; onSet: () => Promise<void> }) {
  const [value, setValue] = useState(limit.enabled ? limit.limit : 0);
  const [failed, setFailed] = useState(false);
  const pick = async (n: number) => {
    const before = value;
    setValue(n); // answer the tap at once; put it back if the server says no
    setFailed(false);
    try {
      await api.setSafetyLimit(limit.lender, limit.borrower, n, n > 0);
      await onSet();
    } catch {
      setValue(before);
      setFailed(true);
    }
  };
  return (
    <View style={s.limitBox}>
      <Text style={s.calloutTitle}>{`You’ll cover ${limit.borrower_name} up to`}</Text>
      <View style={[s.chips, { marginTop: 8 }]}>
        {LIMITS.map((n) => (
          <Chip key={n} on={value === n} label={n === 0 ? 'Off' : money(n, 0)} onPress={() => pick(n)} />
        ))}
      </View>
      <Text style={s.noteText}>
        {failed ? 'Couldn’t save that. Please try again.' : value === 0 ? 'Runway won’t send any of your money automatically.'
          : `Under ${money(value, 0)}, Runway covers ${limit.borrower_name} automatically. Over it, you’re asked first.`}
      </Text>
    </View>
  );
}

/** Demo accounts only: rebuild the demo story and pause automatic help until it's shown live. */
function DemoReset({ onDone }: { onDone: () => void }) {
  const session = useSession();
  const [state, setState] = useState<string | null>(null);
  if (session.mode !== 'signed-in' || !DEMO.includes(session.persona)) return null;
  const reset = async () => {
    setState('Rebuilding Maya, Jordan and Sam… about a minute.');
    try {
      await api.demoReset();
      for (let i = 0; i < 90; i++) {
        await new Promise((r) => setTimeout(r, 3000));
        const st = await api.demoStatus();
        if (st.state === 'done') {
          setState('The demo is fresh. Automatic help is paused until someone taps “Ask family to cover it”.');
          onDone();
          return;
        }
        if (st.state === 'failed') {
          setState(`The reset didn’t finish (${st.error ?? 'error'}). Try again.`);
          return;
        }
      }
      setState('Still rebuilding — refresh in a minute.');
    } catch (e) {
      setState(e instanceof Error && e.message.includes('409') ? 'A reset is already running.' : 'Couldn’t start the reset.');
    }
  };
  return (
    <View style={s.demo}>
      <ActionButton label="Reset demo" confirm="Reset all three demo accounts?" tone="ghost" onPress={reset} />
      {state ? <Text style={s.noteText}>{state}</Text> : null}
    </View>
  );
}

/** "Saturday, October 17" */
const longDay = (iso: string) => fromIso(iso).toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' });

type Tone = 'good' | 'bad' | 'warn' | 'info';
const TONES: Record<Tone, { fg: string; bg: string }> = {
  good: { fg: C.green, bg: 'rgba(63,208,127,0.14)' },
  bad: { fg: C.red, bg: 'rgba(255,90,78,0.14)' },
  warn: { fg: C.amber, bg: 'rgba(245,184,61,0.14)' },
  info: { fg: C.blue, bg: 'rgba(75,157,255,0.14)' },
};

/** A status pill: colour plus words, never colour alone. */
function Pill({ tone, text }: { tone: Tone; text: string }) {
  return (
    <View style={[s.pill, { backgroundColor: TONES[tone].bg }]}>
      <View style={[s.pillDot, { backgroundColor: TONES[tone].fg }]} />
      <Text style={[s.pillText, { color: TONES[tone].fg }]}>{text}</Text>
    </View>
  );
}

/** A plain sentence with a coloured edge: what's happening, in words. */
function Callout({ tone, title, text, children }: PropsWithChildren<{ tone: Tone; title: string; text: string }>) {
  return (
    <View style={[s.callout, { borderLeftColor: TONES[tone].fg, backgroundColor: TONES[tone].bg }]}>
      <Text style={s.calloutTitle}>{title}</Text>
      <Text style={s.calloutText}>{text}</Text>
      {children}
    </View>
  );
}

function Tile({ label, value, sub, tone }: { label: string; value: string; sub: string; tone?: Tone }) {
  return (
    <Glass style={s.tile} grow>
      <Text style={s.tileLabel}>{label}</Text>
      <Text style={[s.tileValue, tone && { color: TONES[tone].fg }]} numberOfLines={1} adjustsFontSizeToFit>{value}</Text>
      <Text style={s.tileSub} numberOfLines={2}>{sub}</Text>
    </Glass>
  );
}

/**
 * A translucent card. On the website it lifts 2px under the pointer on a spring and its edge
 * brightens — a hint that what's inside responds. Phones have no hover, so it stays put.
 */
function Glass({ children, style, grow }: PropsWithChildren<{ style?: StyleProp<ViewStyle>; grow?: boolean }>) {
  const reduced = useReducedMotion();
  const hover = useSharedValue(0);
  const anim = useAnimatedStyle(() => ({
    transform: [{ translateY: -2 * hover.get() }],
    borderColor: interpolateColor(hover.get(), [0, 1], ['rgba(140,165,190,0.16)', 'rgba(140,200,175,0.34)']),
  }));
  const card = <Animated.View style={[s.glass, style, anim]}>{children}</Animated.View>;
  if (Platform.OS !== 'web') return card;
  const to = (v: number) => hover.set(reduced ? v : withSpring(v, { dampingRatio: 1, duration: 350 }));
  return (
    <Pressable onHoverIn={() => to(1)} onHoverOut={() => to(0)} style={grow && { flex: 1 }} accessible={false}>
      {card}
    </Pressable>
  );
}

/** Still glows behind the page (green, blue, violet) — depth without anything drifting. */
export function Glows() {
  return (
    <Svg style={StyleSheet.absoluteFill} pointerEvents="none" preserveAspectRatio="xMidYMid slice" viewBox="0 0 1000 1000">
      <Defs>
        {[['g1', '#1f8f63'], ['g2', '#1e4f9a'], ['g3', '#5a3fa0']].map(([id, c]) => (
          <RadialGradient key={id} id={id} cx="50%" cy="50%" r="50%">
            <Stop offset="0" stopColor={c} stopOpacity={0.32} />
            <Stop offset="1" stopColor={c} stopOpacity={0} />
          </RadialGradient>
        ))}
      </Defs>
      <Circle cx={120} cy={60} r={420} fill="url(#g1)" />
      <Circle cx={940} cy={380} r={400} fill="url(#g2)" />
      <Circle cx={420} cy={980} r={380} fill="url(#g3)" />
    </Svg>
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
    return { cx: cx.get(), cy: yIn(v), opacity: cOn.get(), fill: v < f.safe_floor ? C.red : '#fff' };
  });

  const lowI = f.points.findIndex((p) => p.date === f.low.date);
  const dipping = f.low.balance - spend < f.safe_floor;
  const lineColor = dipping ? '#fff' : C.green; // the line turns green once every day clears the cushion

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
                <Stop offset="0" stopColor={lineColor} stopOpacity={0.14} />
                <Stop offset="1" stopColor="#ffffff" stopOpacity={0} />
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
            <AnimatedCircle cx={xOf(0)} r={5} fill="#fff" animatedProps={todayDot} />
            {lowI >= 0 && dipping && (
              <RidingLabel i={lowI} x={xOf(lowI)} from={from} to={to} morph={morph} offset={offset} yIn={yIn} anchor={anchor}
                text={`${money(f.low.balance - spend, 0)} on ${monthDay(f.low.date)}`} />
            )}
            <AnimatedLine y1={PAD.top - 8} y2={CH - PAD.bottom} stroke="#fff" strokeOpacity={0.5} strokeWidth={1} animatedProps={cursorLine} />
            <AnimatedCircle r={6} stroke={C.card} strokeWidth={2.5} animatedProps={cursorDot} />
          </Svg>
        )}
        <Animated.View pointerEvents="none" style={[s.plane, plane]}>
          <Svg width={26} height={26} viewBox="0 0 24 24" fill="#fff">
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

  glass: { backgroundColor: 'rgba(30,38,48,0.72)', borderWidth: 1, borderColor: 'rgba(140,165,190,0.16)', borderRadius: RADIUS + 4, padding: 22 },
  cardTitle: { ...SYS, fontSize: 19, fontWeight: '600', color: C.text },

  callout: { borderLeftWidth: 3, borderRadius: 10, paddingVertical: 12, paddingHorizontal: 16 },
  actionRow: { flexDirection: 'row', alignItems: 'center', gap: 14 },
  action: { alignSelf: 'flex-start', height: 40, paddingHorizontal: 18, borderRadius: 20, backgroundColor: '#fff', alignItems: 'center', justifyContent: 'center' },
  actionGhost: { backgroundColor: 'transparent', borderWidth: 1, borderColor: 'rgba(140,165,190,0.3)' },
  actionText: { ...SYS, fontSize: 15, fontWeight: '600', color: '#111' },
  cancel: { ...SYS, fontSize: 15, color: C.text2 },
  twoActions: { flexDirection: 'row', gap: 10, marginTop: 10 },
  noteText: { ...SYS, fontSize: 14, lineHeight: 20, color: C.text2, marginTop: 8 },
  limitBox: { borderRadius: 10, paddingVertical: 12, paddingHorizontal: 16, backgroundColor: 'rgba(255,255,255,0.04)', borderWidth: 1, borderColor: 'rgba(140,165,190,0.16)' },
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
  chip: { height: 36, paddingHorizontal: 16, borderRadius: 18, borderWidth: 1, borderColor: 'rgba(140,165,190,0.22)', backgroundColor: 'rgba(255,255,255,0.04)', alignItems: 'center', justifyContent: 'center' },
  chipOn: { backgroundColor: '#fff', borderColor: '#fff' },
  chipText: { ...SYS, fontWeight: '600', fontSize: 15, color: C.text },
  chipTextOn: { color: '#111' },
});

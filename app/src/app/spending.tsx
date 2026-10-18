// Spending — owner: an2thu. Title and month menu, then one of two views (a switch by "Where it went";
// the choice is remembered while the app is open):
//  - Compact: a donut with the total in the middle (tap a slice to filter) and the month's purchases.
//  - Detailed: a bar per category with its change vs last month, every day (Tiger Data continuous
//    aggregate; tap a day), subscriptions (GET /recurring) and the latest purchases.
// Changing the month changes all of it.
// Visual spec: app/prototypes/today-v8.html (Spending tab), colours from constants/runway.ts.
import { type ComponentRef, type ReactNode, useEffect, useRef, useState } from 'react';
import { Dimensions, type GestureResponderEvent, Modal, Pressable, StyleSheet, Text, View } from 'react-native';
import Animated, {
  Easing, type SharedValue, useAnimatedProps, useAnimatedStyle, useReducedMotion, useSharedValue, withDelay, withSpring, withTiming,
} from 'react-native-reanimated';
import Svg, { Circle, Path } from 'react-native-svg';

import { Amount, Avatar, Fine, List, Row, SectionLabel } from '@/components/rw/list';
import { MenuGrow } from '@/components/rw/menu-grow';
import { TopBar } from '@/components/rw/top-bar';
import { LoadState, Page, PressableScale, useWide } from '@/components/rw/ui';
import { alpha, C, F } from '@/constants/runway';
import { useLoad } from '@/hooks/use-load';
import { api } from '@/lib/api';
import { useStore } from '@/lib/store';
import { zoom } from '@/lib/zoom';
import { money, monthName, recentMonths, weekdayDate } from '@/lib/format';
import type { Recurring, Spending, SpendingCompare } from '@/lib/types';

/** One colour per category, biggest first — the app's red, amber, blue, green, then quieter ones. */
const SLICE = [C.red, C.amber, C.blue, C.green, '#a78bfa', '#2bb0c4', '#c2477a', C.slate];
const LATEST = 6; // purchases shown before "Show all"
const MENU_W = 240;

type View_ = 'compact' | 'detailed';
let lastView: View_ = 'compact'; // remembered across tab switches while the app is open

export default function SpendingScreen() {
  const wide = useWide();
  const months = recentMonths(6);
  const [month, setMonth] = useState(months[months.length - 1]);
  const [view, setView] = useState<View_>(lastView);
  const [picked, setPicked] = useState<string | null>(null); // a category tapped on the donut
  const version = useStore().dataVersion; // money moved anywhere: re-fetch
  const sp = useLoad(() => api.spending(month), `${month}:${version}`);
  const subs = useLoad(() => api.recurring(), String(version));
  const isNow = month === months[months.length - 1];
  const d = sp.data;
  const pick = (c: string | null) => setPicked(c === picked ? null : c);
  const changeMonth = (m: string) => { setMonth(m); setPicked(null); };
  const changeView = (v: View_) => { lastView = v; setView(v); setPicked(null); };

  const heading = (
    <View style={s.labelRow}>
      <SectionLabel>Where it went</SectionLabel>
      <ViewSwitch view={view} onChange={changeView} />
    </View>
  );
  const latest = d && <Latest key={month} d={d} picked={view === 'compact' ? picked : null} onClear={() => setPicked(null)} />;
  const credit = <Fine>Transactions from Capital One Nessie.</Fine>;

  let body: ReactNode = null;
  if (d && view === 'compact') {
    const donut = <>{heading}<WhereItWent key={month} d={d} picked={picked} onPick={pick} legend={wide} /></>;
    body = wide
      ? <View style={s.wideRow}><View style={{ flex: 1.2, minWidth: 0 }}>{donut}</View><View style={{ flex: 1, minWidth: 0 }}>{latest}{credit}</View></View>
      : <>{donut}{latest}{credit}</>;
  } else if (d) {
    const bars = <>{heading}<Categories key={month} d={d} /></>;
    const daily = <><SectionLabel>Every day</SectionLabel><Daily d={d} month={month} isNow={isNow} /></>;
    const subsList = <Subscriptions subs={subs.data} />;
    body = wide
      ? <View style={s.wideRow}><View style={{ flex: 1.2, minWidth: 0 }}>{bars}{daily}</View><View style={{ flex: 1, minWidth: 0 }}>{latest}{subsList}{credit}</View></View>
      : <>{bars}{daily}{subsList}{latest}{credit}</>;
  }

  return (
    <Page onRefresh={() => { sp.reload(); subs.reload(); }} refreshing={sp.loading && !!sp.data}>
      <TopBar />
      <View style={s.head}>
        <Text style={s.title} accessibilityRole="header">Spending</Text>
        <MonthMenu months={months} month={month} onChange={changeMonth} now={months[months.length - 1]} />
      </View>
      {!d ? <View style={{ marginTop: 24 }}><LoadState error={sp.error} onRetry={sp.reload} /></View> : (
        // the new view rises into place; the old one is simply replaced, so nothing jumps
        <Rise key={view}>{body}</Rise>
      )}
    </Page>
  );
}

/* ---------------- the view switch ---------------- */

/**
 * The new view rises into place: fades in while moving up 14px and settling from 98.5% scale.
 * Animated by hand rather than with an entering layout animation, which measures in screen pixels and
 * would fix the view's width wrongly on the scaled desktop site. Reduced motion: it simply appears.
 */
function Rise({ children }: { children: ReactNode }) {
  const reduced = useReducedMotion();
  const p = useSharedValue(reduced ? 1 : 0);
  useEffect(() => {
    if (!reduced) p.set(withTiming(1, { duration: 420, easing: Easing.bezier(0.23, 1, 0.32, 1) }));
  }, [reduced, p]);
  const style = useAnimatedStyle(() => ({
    opacity: p.get(),
    transform: [{ translateY: (1 - p.get()) * 14 }, { scale: 0.985 + p.get() * 0.015 }],
  }));
  return <Animated.View style={style}>{children}</Animated.View>;
}

const SEG = 36; // one button of the switch

/** Compact (donut) or Detailed (list): two icons with a thumb that slides between them on a spring. */
function ViewSwitch({ view, onChange }: { view: View_; onChange: (v: View_) => void }) {
  const reduced = useReducedMotion();
  const x = useSharedValue(view === 'compact' ? 0 : SEG);
  useEffect(() => {
    const to = view === 'compact' ? 0 : SEG;
    x.set(reduced ? to : withSpring(to, { dampingRatio: 0.8, duration: 380 }));
  }, [view, reduced, x]);
  const thumb = useAnimatedStyle(() => ({ transform: [{ translateX: x.get() }] }));
  const icon = (v: View_, on: boolean) => {
    const c = on ? C.text : C.text3;
    return v === 'compact' ? (
      <Svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth={2.4} strokeLinecap="round">
        <Circle cx={12} cy={12} r={8} /><Path d="M12 4v8l6 5" />
      </Svg>
    ) : (
      <Svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth={2.4} strokeLinecap="round">
        <Path d="M4 7h16M4 12h11M4 17h7" />
      </Svg>
    );
  };
  return (
    <View style={s.switch} accessibilityRole="tablist">
      <Animated.View style={[s.thumb, thumb]} />
      {(['compact', 'detailed'] as const).map((v) => (
        <Pressable key={v} onPress={() => onChange(v)} style={s.seg} accessibilityRole="tab" hitSlop={4}
          accessibilityState={{ selected: view === v }} accessibilityLabel={v === 'compact' ? 'Compact view' : 'Detailed view'}>
          {icon(v, view === v)}
        </Pressable>
      ))}
    </View>
  );
}

/* ---------------- detailed: a bar per category ---------------- */

/** Each category's share as a bar that grows in, one after another, with its change vs last month. */
function Categories({ d }: { d: Spending }) {
  return (
    <List style={{ paddingVertical: 10 }}>
      {d.compare && <View style={s.chipRow}><VsLastMonth c={d.compare} /></View>}
      {d.categories.length === 0 && <Text style={s.empty}>No purchases this month yet.</Text>}
      {d.categories.map((c, i) => (
        <View key={c.category} style={s.cat} accessible accessibilityLabel={`${c.category}: ${money(c.spent, 0)}, ${pct(c.spent, d.total)}`}>
          <View style={s.catTop}>
            <Text style={s.catName}>{c.category}</Text>
            <View style={s.catRight}>
              <Delta change={d.compare?.categories.find((x) => x.category === c.category)?.change} />
              <Amount>{money(c.spent, 0)}</Amount>
            </View>
          </View>
          <Bar frac={c.spent / Math.max(1, d.categories[0].spent)} color={SLICE[i % SLICE.length]} order={i} />
          <Text style={s.catSub}>{c.purchases} purchase{c.purchases === 1 ? '' : 's'} · {pct(c.spent, d.total)} of the month</Text>
        </View>
      ))}
    </List>
  );
}

function Bar({ frac, color, order }: { frac: number; color: string; order: number }) {
  const reduced = useReducedMotion();
  const w = useSharedValue(reduced ? frac : 0);
  useEffect(() => {
    w.set(reduced ? frac : withDelay(120 + order * 70, withSpring(frac, { dampingRatio: 1, duration: 700 })));
  }, [frac, order, reduced, w]);
  const fill = useAnimatedStyle(() => ({ width: `${Math.max(2, w.get() * 100)}%` }));
  return (
    <View style={s.track}>
      <Animated.View style={[s.fill, { backgroundColor: color }, fill]} />
    </View>
  );
}

/* ---------------- month menu ---------------- */


/** "October ⌄" — a pill that opens the last six months, newest first; the year shows in grey. */
function MonthMenu({ months, month, onChange, now }: { months: string[]; month: string; onChange: (m: string) => void; now: string }) {
  const button = useRef<ComponentRef<typeof View>>(null);
  const [at, setAt] = useState<{ top: number; left: number } | null>(null);
  // measured in on-screen pixels; the menu is placed in layout pixels (they differ on the scaled desktop site)
  // the menu's right edge lines up with the pill's (the pill sits at the right of the title row)
  const open = () => button.current?.measureInWindow((x, y, w, h) => {
    const k = zoom();
    setAt({ top: (y + h) / k + 8, left: Math.max(12, Math.min((x + w) / k - MENU_W, Dimensions.get('window').width / k - MENU_W - 12)) });
  });
  const pick = (m: string) => { onChange(m); setAt(null); };

  return (
    <>
      <View ref={button} collapsable={false}>
        <PressableScale onPress={open} accessibilityRole="button" accessibilityLabel={`${monthName(month)}. Choose a month`}
          accessibilityState={{ expanded: !!at }} style={[s.monthBtn, at && { backgroundColor: C.line2 }]}>
          <Text style={s.monthText}>{monthName(month)}</Text>
          <Svg width={12} height={12} viewBox="0 0 24 24" fill="none" stroke={C.text} strokeWidth={3} strokeLinecap="round" strokeLinejoin="round"
            style={at ? { transform: [{ rotate: '180deg' }] } : undefined}>
            <Path d="m6 9 6 6 6-6" />
          </Svg>
        </PressableScale>
      </View>
      <Modal transparent visible={!!at} onRequestClose={() => setAt(null)} animationType="none">
        <Pressable style={StyleSheet.absoluteFill} onPress={() => setAt(null)} accessibilityLabel="Close menu" />
        {at && (
          <MenuGrow style={[s.menu, { top: at.top, left: at.left }]}>
            <Text style={s.menuHead}>Month</Text>
            {[...months].reverse().map((m) => {
              const on = m === month;
              return (
                <Pressable key={m} onPress={() => pick(m)} accessibilityRole="menuitem" accessibilityState={{ selected: on }}
                  style={({ pressed, hovered }: { pressed: boolean; hovered?: boolean }) => [s.menuItem, on && s.menuItemOn, !on && (pressed || hovered) && { backgroundColor: C.hover }]}>
                  <View style={[s.check, on && s.checkOn]}>
                    {on && (
                      <Svg width={12} height={12} viewBox="0 0 20 20" fill="none" stroke={C.bg} strokeWidth={3} strokeLinecap="round" strokeLinejoin="round">
                        <Path d="M5 10.5l3.5 3.5L15 7" />
                      </Svg>
                    )}
                  </View>
                  <Text style={[s.menuText, on && { color: C.text }]}>{monthName(m)}</Text>
                  <Text style={s.menuSub}>{m === now ? 'So far' : m.slice(0, 4)}</Text>
                </Pressable>
              );
            })}
          </MenuGrow>
        )}
      </Modal>
    </>
  );
}

/* ---------------- where it went: donut + legend ---------------- */

const SIZE = 200;
const STROKE = 26;
const R = (SIZE - STROKE - 10) / 2; // room for a picked slice to thicken without clipping
const CIRC = 2 * Math.PI * R;
const GAP = 3; // px of track between slices, so neighbours read as separate

/** The colour each category gets on the donut, biggest first (the API sends categories biggest first). */
const colorOf = (d: Spending, category: string) => SLICE[Math.max(0, d.categories.findIndex((c) => c.category === category)) % SLICE.length];

/**
 * A donut of the month's spending, total in the middle. Tap a slice: it thickens, the rest dim, the
 * middle shows that category, and the purchases below show only it. Tap it (or the middle) again to clear.
 * Taps are matched by angle and distance from the centre, so the gaps between slices still count.
 */
function WhereItWent({ d, picked, onPick, legend }: { d: Spending; picked: string | null; onPick: (c: string | null) => void; legend: boolean }) {
  const total = d.total || 1;
  // each slice starts where the ones before it end
  const lens = d.categories.map((c) => (c.spent / total) * CIRC);
  const slices = d.categories.map((c, i) => ({
    c, color: SLICE[i % SLICE.length], len: lens[i], offset: lens.slice(0, i).reduce((a, b) => a + b, 0),
  }));
  const sel = slices.find((x) => x.c.category === picked);
  const many = slices.length > 1;
  const ring = useRef<ComponentRef<typeof View>>(null);

  // On open (and each new month) the ring sweeps clockwise from 12 o'clock, slice after slice.
  const reduced = useReducedMotion();
  const sweep = useSharedValue(reduced ? CIRC : 0);
  useEffect(() => {
    if (!reduced) sweep.set(withTiming(CIRC, { duration: 900, easing: Easing.bezier(0.23, 1, 0.32, 1) }));
  }, [reduced, sweep]);

  /** Where the tap landed, measured from the donut itself (an event's own coordinates depend on which part was hit). */
  function onPress(e: GestureResponderEvent) {
    const { pageX, pageY } = e.nativeEvent;
    ring.current?.measureInWindow((x, y) => tap((pageX - x) / zoom(), (pageY - y) / zoom()));
  }

  function tap(x: number, y: number) {
    const dx = x - SIZE / 2, dy = y - SIZE / 2, dist = Math.hypot(dx, dy);
    if (dist < R - STROKE) return onPick(null); // the middle clears the choice
    if (dist > SIZE / 2 + 6) return;
    const along = ((Math.atan2(dy, dx) + Math.PI / 2 + 2 * Math.PI) % (2 * Math.PI)) * R; // clockwise from 12 o'clock
    const hit = slices.find((x) => along >= x.offset && along < x.offset + x.len);
    if (hit) onPick(hit.c.category);
  }

  return (
    <>
      <List style={{ paddingVertical: 18 }}>
        {d.compare && <View style={[s.chipRow, !legend && { alignSelf: 'center' }]}><VsLastMonth c={d.compare} /></View>}
        <View style={legend ? s.donutRow : undefined}>
        {d.categories.length === 0 ? <Text style={s.empty}>No purchases this month yet.</Text> : (
          <>
            <Pressable ref={ring} onPress={onPress} style={s.donutWrap}
              accessibilityRole="adjustable" accessibilityLabel={sel
                ? `${sel.c.category}: ${money(sel.c.spent, 0)}, ${pct(sel.c.spent, d.total)} of ${money(d.total, 0)}`
                : `${money(d.total, 0)} spent: ${d.categories.map((c) => `${c.category} ${pct(c.spent, d.total)}`).join(', ')}`}
              accessibilityActions={[{ name: 'increment' }, { name: 'decrement' }]}
              onAccessibilityAction={(e) => {
                // screen readers step through the categories instead of tapping slices
                const i = slices.findIndex((x) => x.c.category === picked), n = slices.length;
                const next = e.nativeEvent.actionName === 'increment' ? (i + 1) % n : (i - 1 + n) % n;
                onPick(slices[next].c.category);
              }}>
              {/* rotated so the first slice starts at 12 o'clock and the rest go clockwise */}
              <Svg width={SIZE} height={SIZE} style={{ transform: [{ rotate: '-90deg' }] }} pointerEvents="none">
                <Circle cx={SIZE / 2} cy={SIZE / 2} r={R} stroke={C.card2} strokeWidth={STROKE} fill="none" />
                {slices.map(({ c, color, len, offset: o }) => (
                  <Slice key={c.category} color={color} len={Math.max(0.5, len - (many ? GAP : 0))} offset={o} sweep={sweep}
                    on={sel?.c.category === c.category} dim={!!sel && sel.c.category !== c.category} />
                ))}
              </Svg>
              <View style={s.donutMid} pointerEvents="none">
                {sel && <Text style={[s.midName, { color: sel.color }]} numberOfLines={1}>{sel.c.category}</Text>}
                <Text style={s.midValue}>{money(sel ? sel.c.spent : d.total, 0)}</Text>
                <Text style={s.midLabel}>{sel
                  ? `${pct(sel.c.spent, d.total)} · ${sel.c.purchases} purchase${sel.c.purchases === 1 ? '' : 's'}`
                  : 'Tap a slice'}</Text>
                {sel && <Delta change={d.compare?.categories.find((x) => x.category === sel.c.category)?.change} vs={d.compare?.previous_month} />}
              </View>
            </Pressable>
            {legend && (
              <View style={{ flex: 1 }}>
                {slices.map(({ c, color }, i) => (
                  <Pressable key={c.category} onPress={() => onPick(c.category)} accessibilityRole="button"
                    accessibilityState={{ selected: picked === c.category }}
                    style={[s.leg, i > 0 && s.legLine, sel && sel.c.category !== c.category && { opacity: 0.45 }]}>
                    <View style={[s.dot, { backgroundColor: color }]} />
                    <View style={{ flex: 1 }}>
                      <View style={s.legTop}>
                        <Text style={s.legName}>{c.category}</Text>
                        <Delta change={d.compare?.categories.find((x) => x.category === c.category)?.change} />
                      </View>
                      <Text style={s.legSub}>{c.purchases} purchase{c.purchases === 1 ? '' : 's'}</Text>
                    </View>
                    <View style={{ alignItems: 'flex-end' }}>
                      <Amount>{money(c.spent, 0)}</Amount>
                      <Text style={s.legSub}>{pct(c.spent, d.total)}</Text>
                    </View>
                  </Pressable>
                ))}
              </View>
            )}
          </>
        )}
        </View>
      </List>
    </>
  );
}

const AnimatedCircle = Animated.createAnimatedComponent(Circle);

/** One slice: drawn as far as the sweep has reached, thicker when picked, faded when another is. */
function Slice({ color, len, offset, sweep, on, dim }: { color: string; len: number; offset: number; sweep: SharedValue<number>; on: boolean; dim: boolean }) {
  const props = useAnimatedProps(() => {
    const shown = Math.min(len, Math.max(0, sweep.get() - offset));
    return { strokeDasharray: [Math.max(0.01, shown), CIRC] };
  });
  return (
    <AnimatedCircle cx={SIZE / 2} cy={SIZE / 2} r={R} fill="none" stroke={color} strokeWidth={on ? STROKE + 8 : STROKE}
      strokeDashoffset={-offset} opacity={dim ? 0.25 : 1} animatedProps={props} />
  );
}

const pct = (part: number, whole: number) => (whole ? `${Math.round((part / whole) * 100)}%` : '—');

/* ---------------- the rest ---------------- */

/**
 * The month's purchases, newest first — or only the category picked on the donut. Each one has a dot
 * in its category's colour, so it matches the slice it belongs to.
 */
function Latest({ d, picked, onClear }: { d: Spending; picked: string | null; onClear: () => void }) {
  const [all, setAll] = useState(false);
  const list = picked ? d.transactions.filter((t) => t.category === picked) : d.transactions;
  const shown = all ? list : list.slice(0, LATEST);
  return (
    <>
      <View style={s.latestHead}>
        <SectionLabel>{picked ? `${picked} · ${list.length} purchase${list.length === 1 ? '' : 's'}` : 'Transactions'}</SectionLabel>
        {picked && (
          <Pressable onPress={onClear} accessibilityRole="button" hitSlop={10} style={s.clear}>
            <Text style={s.clearText}>Show all</Text>
          </Pressable>
        )}
      </View>
      <List>
        {list.length === 0 && <Row first title="No purchases this month." />}
        {shown.map((t, i) => (
          <Row key={`${t.date}-${t.merchant}-${i}`} first={i === 0}
            left={<View><Avatar name={t.merchant} /><View style={[s.tag, { backgroundColor: colorOf(d, t.category) }]} /></View>}
            title={t.merchant} sub={`${t.category} · ${weekdayDate(t.date)}`} right={<Amount>{money(-t.amount, 2)}</Amount>} />
        ))}
        {list.length > LATEST && (
          <Pressable onPress={() => setAll(!all)} accessibilityRole="button" style={s.more}>
            <Text style={s.moreText}>{all ? 'Show fewer' : `Show all ${list.length}`}</Text>
          </Pressable>
        )}
      </List>
    </>
  );
}

/** Spending per day across the whole month, so the axis is honest; today in white. */
/**
 * Spending per day this month. Tap a bar (or hover it on the website) to see that day: the total and
 * what was bought. Tap it again, or the summary, to go back to the month. Future days are drawn flat.
 */
function Daily({ d, month, isNow }: { d: Spending; month: string; isNow: boolean }) {
  const [picked, setPicked] = useState<number | null>(null);
  const [y, m] = month.split('-').map(Number);
  const daysIn = new Date(y, m, 0).getDate();
  const lastDay = isNow ? new Date().getDate() : daysIn;
  const byDay = new Map(d.daily.map((x) => [Number(x.date.slice(8, 10)), x.spent]));
  const max = Math.max(1, ...d.daily.map((x) => x.spent));
  const bought = picked ? d.transactions.filter((t) => Number(t.date.slice(8, 10)) === picked) : [];
  const pickedDate = picked ? `${y}-${String(m).padStart(2, '0')}-${String(picked).padStart(2, '0')}` : null;
  return (
    <List style={{ paddingVertical: 14 }}>
      <PressableScale onPress={() => setPicked(null)} accessibilityRole="button" accessibilityLabel="Show the whole month">
        <Text style={s.dailySub}>
          {picked && pickedDate
            ? `${weekdayDate(pickedDate)} · ${money(byDay.get(picked) ?? 0, 0)} · ${bought.length} ${bought.length === 1 ? 'purchase' : 'purchases'}`
            : `${d.transactions.length} purchases · about ${money(d.total / Math.max(1, lastDay), 0)} a day`}
        </Text>
      </PressableScale>
      <View style={s.bars} accessibilityLabel="Daily spending">
        {Array.from({ length: daysIn }, (_, i) => {
          const day = i + 1, v = byDay.get(day) ?? 0, future = day > lastDay, today = isNow && day === lastDay;
          const on = picked === day;
          const color = future ? C.line : on || (today && !picked) ? C.text : C.slate;
          const opacity = future ? 1 : on ? 1 : picked ? 0.3 : today ? 1 : 0.55;
          return (
            <Pressable key={day} disabled={future} onPress={() => setPicked(on ? null : day)}
              onHoverIn={() => !future && setPicked(day)}
              accessibilityRole="button" accessibilityLabel={`${monthName(month, 'short')} ${day}: ${money(v, 0)}`}
              style={s.barHit}>
              <View style={[s.bar, { height: future ? 4 : `${Math.max(4, (v / max) * 100)}%`, backgroundColor: color, opacity }]} />
            </Pressable>
          );
        })}
      </View>
      <View style={s.axis}>
        <Text style={s.axisText}>{monthName(month, 'short')} 1</Text>
        <Text style={s.axisText}>{monthName(month, 'short')} {daysIn}</Text>
      </View>
      {picked !== null && (
        <View style={s.dayList}>
          {bought.length === 0 ? <Text style={s.dailySub}>Nothing bought that day.</Text> : bought.map((t, k) => (
            <View key={`${t.merchant}-${k}`} style={s.dayRow}>
              <Text style={s.dayMerchant} numberOfLines={1}>{t.merchant}</Text>
              <Text style={s.dayCat}>{t.category}</Text>
              <Amount>{money(t.amount)}</Amount>
            </View>
          ))}
        </View>
      )}
    </List>
  );
}

function Subscriptions({ subs }: { subs: Recurring[] | null }) {
  if (!subs?.length) return null;
  // Normalise each charge to a 30-day month, as the backend's interval_days describes it.
  const monthly = subs.reduce((t, r) => t + r.amount * (30 / r.interval_days), 0);
  return (
    <>
      <SectionLabel>Subscriptions · {money(monthly)} a month</SectionLabel>
      <List>
        {subs.map((r, i) => (
          <Row key={r.merchant} first={i === 0} left={<Avatar name={r.merchant} />} title={r.merchant}
            sub={`Next ${weekdayDate(r.next_date)}`} right={<Amount>{money(r.amount)}</Amount>} />
        ))}
      </List>
    </>
  );
}

/**
 * One line against last month — the SAME days of it while this month is in progress, so a half-done
 * month never looks like "spending less" just because it isn't over. Green when less, amber when more.
 */
function VsLastMonth({ c }: { c: SpendingCompare }) {
  const span = `${monthName(c.previous_month, 'short')}${c.through_day ? ` 1–${c.through_day}` : ''}`;
  const amount = money(Math.abs(c.change), 0);
  const [text, tone] = Math.abs(c.change) < 1 ? [`Same as ${span}`, C.text2]
    : c.change < 0 ? [`${amount} less than ${span}`, C.green]
    : [`${amount} more than ${span}`, C.amber];
  const arrow = Math.abs(c.change) < 1 ? '→ ' : c.change < 0 ? '↓ ' : '↑ '; // level, down or up: always a result, never just a label
  return (
    <View style={[s.vsChip, { backgroundColor: alpha(tone, '1f') }]} accessible accessibilityLabel={`Compared with last month: ${text}`}>
      <Text style={[s.vs, { color: tone }]} numberOfLines={1}>{arrow}{text}</Text>
    </View>
  );
}

/** A category's change against the same days last month: "−$30" (less) or "+$18" (more), "vs Sep" in the donut. */
function Delta({ change, vs }: { change?: number; vs?: string }) {
  if (change === undefined || Math.abs(change) < 1) return null;
  const less = change < 0;
  return (
    <Text style={[s.delta, { color: less ? C.green : C.amber }]} accessibilityLabel={`${money(Math.abs(change), 0)} ${less ? 'less' : 'more'} than last month`}>
      {`${less ? '−' : '+'}${money(Math.abs(change), 0)}${vs ? ` vs ${monthName(vs, 'short')}` : ''}`}
    </Text>
  );
}

const s = StyleSheet.create({
  switch: { flexDirection: 'row', padding: 3, borderRadius: 999, backgroundColor: C.card, marginBottom: 6 },
  thumb: { position: 'absolute', top: 3, left: 3, width: SEG, height: 30, borderRadius: 999, backgroundColor: C.card2 },
  seg: { width: SEG, height: 30, alignItems: 'center', justifyContent: 'center' },
  chipRow: { alignSelf: 'flex-start', marginBottom: 10 },
  catRight: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  catSub: { fontFamily: F.body, fontSize: 12, color: C.text3, marginTop: 5 },
  cat: { paddingVertical: 9 },
  catTop: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  catName: { fontFamily: F.bodySemi, fontSize: 16, color: C.text },
  track: { height: 8, borderRadius: 4, backgroundColor: C.card2, marginTop: 7, overflow: 'hidden' },
  fill: { height: '100%', borderRadius: 4 },
  head: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginTop: 26 },
  labelRow: { flexDirection: 'row', alignItems: 'flex-end', justifyContent: 'space-between', gap: 10 },
  vsChip: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: 999, flexShrink: 1 },
  vs: { fontFamily: F.bodySemi, fontSize: 13 },
  donutRow: { flexDirection: 'row', alignItems: 'center', gap: 28, paddingHorizontal: 22 },
  delta: { fontFamily: F.condBold, fontSize: 14 },
  legTop: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  barHit: { flex: 1, height: '100%', justifyContent: 'flex-end' },
  dayList: { marginTop: 12, paddingTop: 10, borderTopWidth: 1, borderTopColor: C.line, gap: 8 },
  dayRow: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  dayMerchant: { flex: 1, fontFamily: F.bodySemi, fontSize: 14, color: C.text },
  dayCat: { fontFamily: F.body, fontSize: 13, color: C.text2 },
  wideRow: { flexDirection: 'row', gap: 24, alignItems: 'flex-start' },
  title: { fontFamily: F.bodySemi, fontSize: 30, letterSpacing: -0.6, color: C.text, paddingHorizontal: 2 },
  monthBtn: { flexDirection: 'row', alignItems: 'center', gap: 8, height: 38, paddingLeft: 16, paddingRight: 14, borderRadius: 999, backgroundColor: C.card2 },
  monthText: { fontFamily: F.bodySemi, fontSize: 15, color: C.text },
  menu: {
    position: 'absolute', width: MENU_W, padding: 8, borderRadius: 22, backgroundColor: C.card2, transformOrigin: 'top right',
    borderWidth: 1, borderColor: C.hover,
    shadowColor: '#000', shadowOpacity: 0.5, shadowRadius: 40, shadowOffset: { width: 0, height: 14 }, elevation: 20,
  },
  menuHead: { fontFamily: F.cond, fontSize: 12, letterSpacing: 1.6, textTransform: 'uppercase', color: C.text3, paddingHorizontal: 12, paddingTop: 6, paddingBottom: 8 },
  menuItem: { flexDirection: 'row', alignItems: 'center', gap: 12, height: 46, paddingHorizontal: 12, borderRadius: 14 },
  menuItemOn: { backgroundColor: C.hover },
  menuText: { flex: 1, fontFamily: F.bodySemi, fontSize: 16, color: C.text2 },
  menuSub: { fontFamily: F.body, fontSize: 13, color: C.text3 },
  check: { width: 20, height: 20, borderRadius: 10, borderWidth: 1.5, borderColor: C.grab, alignItems: 'center', justifyContent: 'center' },
  checkOn: { backgroundColor: C.green, borderColor: C.green },
  empty: { fontFamily: F.body, fontSize: 15, color: C.text2, paddingVertical: 10 },
  donutWrap: { alignSelf: 'center', width: SIZE, height: SIZE },
  donutMid: { ...StyleSheet.absoluteFill, alignItems: 'center', justifyContent: 'center' },
  midName: { fontFamily: F.bodySemi, fontSize: 13, maxWidth: SIZE - STROKE * 2 - 8 },
  midValue: { fontFamily: F.condBold, fontSize: 32, color: C.text, fontVariant: ['tabular-nums'] },
  midLabel: { fontFamily: F.body, fontSize: 13, color: C.text2, maxWidth: SIZE - STROKE * 2 - 8, textAlign: 'center' },
  leg: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 10 },
  legLine: { borderTopWidth: 1, borderTopColor: C.line },
  dot: { width: 12, height: 12, borderRadius: 6 },
  legName: { fontFamily: F.bodySemi, fontSize: 16, color: C.text },
  legSub: { fontFamily: F.body, fontSize: 13, color: C.text2 },
  latestHead: { flexDirection: 'row', alignItems: 'flex-end', justifyContent: 'space-between' },
  clear: { marginBottom: 10, marginRight: 2 },
  clearText: { fontFamily: F.bodySemi, fontSize: 14, color: C.blue },
  tag: { position: 'absolute', right: -1, bottom: -1, width: 12, height: 12, borderRadius: 6, borderWidth: 2, borderColor: C.card },
  more: { borderTopWidth: 1, borderTopColor: C.line, paddingVertical: 12, alignItems: 'center' },
  moreText: { fontFamily: F.bodySemi, fontSize: 14, color: C.blue },
  dailySub: { fontFamily: F.body, fontSize: 14, color: C.text2 },
  bars: { flexDirection: 'row', alignItems: 'flex-end', gap: 3, height: 72, marginTop: 14 },
  bar: { width: '100%', borderRadius: 2, minHeight: 2 },
  axis: { flexDirection: 'row', justifyContent: 'space-between', marginTop: 6 },
  axisText: { fontFamily: F.body, fontSize: 12, color: C.text3 },
});

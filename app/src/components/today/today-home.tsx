/**
 * Today: where you stand, and how to fix it (visual spec: app/prototypes/today-v8.html).
 *  - the balance, centred; it follows your finger along the chart
 *  - one status pill ("You're fine until Thu, Oct 22"); tap it for each dip, what causes it, and a fix
 *  - three tiles: next payday, spare money today, lowest point
 *  - the newest family safety-net note, which you can close
 *  - the 30-day line with "What if I spend today" ($20 / $50 / $100 / your own amount) and
 *    "Cover this dip", which asks the agent for a fix and opens the approval sheet
 *  - Coming up: bills and pay in the next two weeks; each row points at its day on the chart
 *
 * Every number comes from GET /forecast, GET /me and GET /safety-net. The fix is the agent's
 * proposal (POST /agent/chat "Fix it"); nothing moves until the user approves it in the sheet.
 */
import { router } from 'expo-router';
import { useState } from 'react';
import { Platform, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import Animated, { FadeIn, FadeOut, LinearTransition, useReducedMotion } from 'react-native-reanimated';
import Svg, { Path } from 'react-native-svg';

import { openApproval } from '@/components/rw/approval-sheet';
import { Icon } from '@/components/rw/icons';
import { Amount, Avatar, List, Row, SectionLabel } from '@/components/rw/list';
import { PressableScale } from '@/components/rw/ui';
import { BalanceChart } from '@/components/today/today-interactive';
import { C, F } from '@/constants/runway';
import { useLoad } from '@/hooks/use-load';
import { api } from '@/lib/api';
import { money, monthDay, weekdayDate } from '@/lib/format';
import { isClear, nextPaycheck, runwayDays, safeToSpend, upcoming } from '@/lib/runway';
import { useStore } from '@/lib/store';
import type { Forecast, ForecastEvent, Me, SafetyNetSummary, SupportSummary } from '@/lib/types';

const WHAT_IFS = [20, 50, 100];
const CUSTOM_MAX = 5000;
const EASE = LinearTransition.springify().damping(30).stiffness(260); // critically damped-ish, no bounce

/** The forecast as it would be with `delta` more (or less) in checking from today on. Display only. */
function shifted(f: Forecast, delta: number): Forecast {
  if (!delta) return f;
  const points = f.points.map((p) => ({ ...p, balance: p.balance + delta }));
  const low = points.reduce((m, p) => (p.balance < m.balance ? p : m), points[0]);
  return { ...f, points, low };
}

/** Bills and pay on a day (everyday spending left out). */
export const eventsOn = (f: Forecast, date: string) => f.events.filter((e) => e.date === date && e.kind !== 'spending');
export const describe = (es: ForecastEvent[]) => es.map((e) => `${e.label} ${e.amount > 0 ? '+' : '−'}${money(Math.abs(e.amount), 0)}`).join(' · ');

export function TodayHome({ f, wide, takeoff }: { f: Forecast; wide: boolean; takeoff: number }) {
  const store = useStore();
  const me = useLoad(() => api.me(), String(store.dataVersion));
  const family = useLoad(() => api.safetyNet(), String(store.dataVersion));
  const support = useLoad(() => api.support(), String(store.dataVersion));
  const [spend, setSpend] = useState(0);
  const [scrub, setScrub] = useState<number | null>(null);
  const [rowDate, setRowDate] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  const view = shifted(f, -spend);
  const focusIndex = rowDate ? f.points.findIndex((p) => p.date === rowDate) : -1;
  const day = scrub ?? (focusIndex >= 0 ? focusIndex : null);
  const point = day ? view.points[day] : null; // day 0 is today: the default view

  const hero = <Hero view={view} spend={spend} point={point} open={open} onToggle={() => setOpen(!open)} />;
  const details = open ? <Details view={view} f={f} spend={spend} me={me.data} approved={store.approvedAmount} /> : null;
  const net = safetyNetLine(family.data, support.data);

  const chart = (
    <View>
      <SectionLabel>Next 30 days</SectionLabel>
      <View style={s.card}>
        <BalanceChart f={f} spend={spend} ghost={null} focusIndex={focusIndex >= 0 ? focusIndex : null} onScrub={setScrub} takeoff={takeoff} />
        <WhatIf spend={spend} onChange={setSpend} />
        <Fix f={f} me={me.data} approved={store.approvedAmount} />
      </View>
    </View>
  );
  const notes = net ? (
    <Animated.View entering={FadeIn.duration(200)} layout={EASE} style={{ marginTop: 14 }}>
      <SectionLabel>Your safety net</SectionLabel>
      <PressableScale onPress={() => router.navigate('/circles')} accessibilityRole="button"
        accessibilityLabel={`${net.title}. Manage protection`} style={s.note}>
        <Avatar tint={net.tint}><Icon name="shield" size={18} color={net.tint} /></Avatar>
        <View style={{ flex: 1 }}>
          <Text style={s.noteTitle}>{net.title}</Text>
          <Text style={s.noteSub}>{net.sub}</Text>
        </View>
        <Text style={s.manage}>Manage</Text>
      </PressableScale>
    </Animated.View>
  ) : null;
  const coming = <ComingUp f={f} selected={point?.date ?? null} onFocus={setRowDate} />;

  return (
    <View>
      {hero}
      {details}
      <Animated.View layout={EASE}>
        <Tiles view={view} f={f} />
        {wide ? (
          <View style={s.wideRow}>
            <View style={{ flex: 1.45 }}>{chart}</View>
            <View style={{ flex: 1 }}>{notes}{coming}</View>
          </View>
        ) : (
          <>{notes}{chart}{coming}</>
        )}
      </Animated.View>
    </View>
  );
}

/* ---------------- the top: balance + status pill ---------------- */

function Hero({ view, spend, point, open, onToggle }: {
  view: Forecast; spend: number; point: Forecast['points'][number] | null; open: boolean; onToggle: () => void;
}) {
  const covered = isClear(view);
  const first = runwayDays(view);
  const you = spend ? 'You’d be' : 'You’re';
  const status = covered ? `${you} covered all month`
    : first === 0 ? `${you} under ${money(view.safe_floor, 0)} today`
    : `${you} fine until ${weekdayDate(view.points[first].date)}`;
  const events = point ? eventsOn(view, point.date) : [];
  const tone = covered ? C.green : C.red;

  return (
    <View style={s.hero}>
      <Text style={[s.bal, point && point.balance < view.safe_floor && { color: C.red }]} accessibilityLiveRegion="polite">
        {money(point ? point.balance : view.points[0].balance, 0)}
      </Text>
      <Text style={s.balLabel}>{point ? weekdayDate(point.date) : spend ? `If you spend ${money(spend, 0)} today` : 'In checking'}</Text>
      <Text style={s.evLine}>{point ? (events.length ? describe(events) : 'Everyday spending only') : ' '}</Text>
      <PressableScale onPress={onToggle} accessibilityRole="button" accessibilityState={{ expanded: open }}
        accessibilityHint="Shows what's behind this" style={[s.pill, { backgroundColor: `${tone}22` }]}>
        <View style={[s.pillDot, { backgroundColor: tone }]} />
        <Text style={[s.pillText, { color: tone }]}>{status}</Text>
        <Svg width={12} height={12} viewBox="0 0 24 24" fill="none" stroke={tone} strokeWidth={3} strokeLinecap="round" strokeLinejoin="round"
          style={open ? { transform: [{ rotate: '180deg' }] } : undefined}>
          <Path d="m6 9 6 6 6-6" />
        </Svg>
      </PressableScale>
    </View>
  );
}

/** Behind the pill: each day you'd go under your cushion and why, then the lowest point and the fix. */
function Details({ view, f, spend, me, approved }: { view: Forecast; f: Forecast; spend: number; me: Me | null; approved: number }) {
  const reduced = useReducedMotion();
  const floor = money(view.safe_floor, 0);
  const drops = view.points.filter((p, i) => p.balance < view.safe_floor && (i === 0 || view.points[i - 1].balance >= view.safe_floor));
  const lowEvents = eventsOn(view, view.low.date);
  return (
    <Animated.View entering={reduced ? undefined : FadeIn.duration(260)} exiting={reduced ? undefined : FadeOut.duration(160)} style={s.details}>
      {drops.length === 0 ? (
        <>
          <Text style={s.dText}>Your lowest point is <Text style={s.b}>{money(view.low.balance, 0)}</Text> on {weekdayDate(view.low.date)}, still above the <Text style={s.b}>{floor}</Text> you keep for surprises.</Text>
          {approved > 0 && <Text style={[s.dText, s.dFoot]}>Thanks to the {money(approved, 0)} you moved from savings today.</Text>}
        </>
      ) : (
        <>
          <Text style={s.dText}>You go under the <Text style={s.b}>{floor}</Text> you keep for surprises {drops.length === 1 ? 'once' : `${drops.length} times`} this month:</Text>
          {drops.map((p) => (
            <View key={p.date} style={s.dRow}>
              <View style={{ flex: 1 }}>
                <Text style={s.dDay}>{weekdayDate(p.date)}</Text>
                <Text style={s.dWhy}>{describe(eventsOn(view, p.date)) || 'Everyday spending'}</Text>
              </View>
              <Amount tone="red">{money(p.balance, 0)}</Amount>
            </View>
          ))}
          <Text style={[s.dText, s.dFoot]}>
            Lowest: <Text style={[s.b, { color: C.red }]}>{money(view.low.balance, 0)}</Text> on {weekdayDate(view.low.date)}{lowEvents.length ? ` (${describe(lowEvents)})` : ''}.
          </Text>
          {!spend && <Fix f={f} me={me} approved={approved} compact />}
        </>
      )}
    </Animated.View>
  );
}

/* ---------------- tiles ---------------- */

function Tiles({ view, f }: { view: Forecast; f: Forecast }) {
  const pay = nextPaycheck(f);
  const spare = safeToSpend(view);
  const low = view.low.balance < view.safe_floor;
  return (
    <View style={s.tiles}>
      <Tile label="Next payday" value={pay ? money(pay.amount, 0) : 'None'} sub={pay ? weekdayDate(pay.date) : 'in the next month'} />
      <Tile label="Spare today" value={money(spare, 0)} sub={spare > 0 ? 'after bills' : 'wait for payday'} />
      <Tile label="Lowest point" value={money(view.low.balance, 0)} sub={monthDay(view.low.date)} red={low} />
    </View>
  );
}

function Tile({ label, value, sub, red }: { label: string; value: string; sub: string; red?: boolean }) {
  return (
    <View style={s.tile} accessible accessibilityLabel={`${label}: ${value}, ${sub}`}>
      <Text style={s.tileLabel}>{label}</Text>
      <Text style={[s.tileValue, red && { color: C.red }]} numberOfLines={1} adjustsFontSizeToFit>{value}</Text>
      <Text style={s.tileSub} numberOfLines={1}>{sub}</Text>
    </View>
  );
}

/* ---------------- what if ---------------- */

/** "What if I spend today": $20 / $50 / $100, or type your own. Tap the chosen one again to clear. */
function WhatIf({ spend, onChange }: { spend: number; onChange: (n: number) => void }) {
  const [typing, setTyping] = useState(false);
  const [text, setText] = useState('');
  const custom = spend > 0 && !WHAT_IFS.includes(spend);

  function apply() {
    setTyping(false);
    const n = Math.round(Number(text.replace(/[^0-9.]/g, '')));
    onChange(n > 0 ? Math.min(n, CUSTOM_MAX) : 0);
  }

  return (
    <View style={s.whatIf}>
      <Text style={s.whatIfLabel}>What if I spend today:</Text>
      {WHAT_IFS.map((n) => (
        <Chip key={n} on={spend === n} label={money(n, 0)} onPress={() => onChange(spend === n ? 0 : n)} />
      ))}
      {typing ? (
        <View style={[s.chip, s.chipOn, s.customBox]}>
          <Text style={[s.chipText, { color: C.text3 }]}>$</Text>
          <TextInput autoFocus value={text} onChangeText={setText} onSubmitEditing={apply} onBlur={apply}
            keyboardType="decimal-pad" returnKeyType="done" placeholder="0" placeholderTextColor="#9aa1a8"
            accessibilityLabel="Your own amount" style={s.customInput} maxLength={6} />
        </View>
      ) : (
        <Chip on={custom} label={custom ? money(spend, 0) : 'Custom'}
          onPress={() => { setText(custom ? String(spend) : ''); setTyping(true); }} />
      )}
    </View>
  );
}

function Chip({ on, label, onPress }: { on: boolean; label: string; onPress: () => void }) {
  return (
    <PressableScale onPress={onPress} accessibilityRole="button" accessibilityState={{ selected: on }}
      accessibilityLabel={label === 'Custom' ? 'What if I spend my own amount today' : `What if I spend ${label} today`}
      style={[s.chip, on && s.chipOn]}>
      <Text style={[s.chipText, on && { color: '#111' }]}>{label}</Text>
    </PressableScale>
  );
}

/* ---------------- the fix ---------------- */

/**
 * "Cover this dip": asks the agent for a fix, then opens the approval sheet with the facts.
 * After an approval: a quiet "Done" line instead.
 */
export function Fix({ f, me, approved, compact }: { f: Forecast; me: Me | null; approved: number; compact?: boolean }) {
  const [asking, setAsking] = useState(false);
  const [failed, setFailed] = useState(false);

  if (isClear(f)) {
    if (!approved || compact) return null;
    return (
      <View style={s.done}>
        <Avatar tint={C.green}><Icon name="check" size={18} color={C.green} /></Avatar>
        <View style={{ flex: 1 }}>
          <Text style={s.doneSub}>Done · approved just now</Text>
          <Text style={s.doneTitle}>Moved {money(approved, 0)} from savings</Text>
        </View>
      </View>
    );
  }

  async function getFix() {
    setAsking(true);
    setFailed(false);
    try {
      const r = await api.chat('Fix it');
      const a = r.pending_action;
      if (!a) {
        setFailed(true);
        return;
      }
      const amount = a.amount ?? 0;
      const savings = me?.accounts.find((x) => x.type === 'Savings');
      const after = shifted(f, amount); // display only: the forecast lifted by the move, as Today shows it after approval
      openApproval({
        action: a,
        title: a.kind === 'transfer' ? `Move ${money(amount, 0)} from savings` : a.description,
        lead: isClear(after) ? 'Covers every dip. You’ll be okay all month.' : `Helps, but you’d still dip on ${weekdayDate(after.points[runwayDays(after)].date)}.`,
        facts: [
          ...(savings ? [['From', `Savings · ${money(savings.balance, 0)} → ${money(savings.balance - amount, 0)}`] as [string, string]] : [['From', 'Savings'] as [string, string]]),
          ['To', 'Checking'],
          ['When', 'Today'],
          ['Lowest point after', `${money(after.low.balance, 0)} on ${weekdayDate(after.low.date)}`],
        ],
      });
    } catch {
      setFailed(true);
    } finally {
      setAsking(false);
    }
  }

  return (
    <View style={{ marginTop: compact ? 12 : 16 }}>
      <PressableScale onPress={getFix} disabled={asking} accessibilityRole="button" style={[s.cta, compact && { height: 46 }, asking && { opacity: 0.6 }]}>
        <Text style={s.ctaText}>{asking ? 'Finding a fix…' : 'Cover this dip'}</Text>
      </PressableScale>
      {!compact && (
        <Text style={s.fixNote}>
          {failed ? 'Couldn’t find a fix. Try again, or ask in the chat.' : 'We’ll suggest moving money from savings. Nothing moves until you say yes.'}
        </Text>
      )}
      {compact && failed && <Text style={s.fixNote}>Couldn’t find a fix. Try again, or ask in the chat.</Text>}
    </View>
  );
}

/* ---------------- coming up ---------------- */

/** Bills and pay in the next two weeks. Hover or press a row to point at its day on the chart. */
function ComingUp({ f, selected, onFocus }: { f: Forecast; selected: string | null; onFocus: (date: string | null) => void }) {
  const items = upcoming(f);
  return (
    <View>
      <SectionLabel>Coming up</SectionLabel>
      <List>
        {items.length === 0 && <Row first title="Nothing due in the next two weeks." />}
        {items.map((e, i) => (
          <Pressable key={`${e.date}-${e.label}-${i}`} onHoverIn={() => onFocus(e.date)} onHoverOut={() => onFocus(null)}
            onPressIn={() => onFocus(e.date)} onPressOut={() => Platform.OS !== 'web' && onFocus(null)}
            accessibilityRole="button"
            accessibilityLabel={`${weekdayDate(e.date)}, ${e.label}, ${e.amount > 0 ? 'plus' : 'minus'} ${money(Math.abs(e.amount), 0)}. Show on the chart.`}>
            <Row first={i === 0} highlight={selected === e.date} title={e.label} sub={weekdayDate(e.date)}
              right={<Amount tone={e.amount > 0 ? 'green' : undefined}>{`${e.amount > 0 ? '+' : '−'}${money(Math.abs(e.amount), 0)}`}</Amount>} />
          </Pressable>
        ))}
      </List>
    </View>
  );
}

const STILL_OUT = ['funding', 'active', 'repaying', 'repay_failed', 'reconcile'];

/**
 * The one-line state of MY safety net — only my own side: what I received and owe, or what I gave and
 * am owed, or who's ready to help. Never anyone else's money.
 */
function safetyNetLine(d: SafetyNetSummary | null, sup: SupportSummary | null): { title: string; sub: string; tint: string } | null {
  if (!d || !sup) return null;
  const borrowed = d.borrowed.filter((b) => STILL_OUT.includes(b.status));
  const lent = d.lent.filter((b) => STILL_OUT.includes(b.status));
  if (borrowed.length) {
    const total = borrowed.reduce((t, b) => t + b.amount, 0);
    const who = borrowed.length === 1 ? borrowed[0].lender_name : `${borrowed.length} people`;
    return { title: `Your safety net is active: ${money(total, 0)} from ${who}`, sub: 'Repayment is expected after your next verified payday.', tint: C.green };
  }
  if (d.approvals_waiting.length) {
    const b = d.approvals_waiting[0];
    return { title: `${b.borrower_name} could use ${money(b.amount, 0)} of support`, sub: 'Over your automatic limit — it’s your call.', tint: C.amber };
  }
  if (lent.length) {
    const total = lent.reduce((t, b) => t + b.amount, 0);
    const who = lent.map((b) => b.borrower_name).join(' and ');
    return { title: `Your support is active: ${money(total, 0)} with ${who}`, sub: `Expected back ${weekdayDate(lent[0].due_date)}.`, tint: '#7cb8ff' };
  }
  const offers = [...sup.supporters, ...sup.supporting].filter((a) => !a.i_agreed && a.they_agreed);
  if (offers.length) return { title: 'Someone is waiting for your answer', sub: 'Review a Quiet Support Agreement.', tint: C.amber };
  const ready = sup.supporters.filter((a) => a.state === 'active');
  if (ready.length) {
    return { title: 'Your trusted circle is ready', sub: `${ready.length === 1 ? ready[0].supporter_name : `${ready.length} people`} agreed to cover a short gap — without seeing your money.`, tint: C.green };
  }
  if (sup.supporting.some((a) => a.state === 'active')) {
    return { title: 'You’re someone’s safety net', sub: 'Runway only uses your help when your own bills stay covered.', tint: '#7cb8ff' };
  }
  return null;
}

const s = StyleSheet.create({
  wideRow: { flexDirection: 'row', gap: 24, alignItems: 'flex-start' },

  hero: { alignItems: 'center', marginTop: 34 },
  bal: { fontFamily: F.condBold, fontSize: 64, lineHeight: 68, color: C.text, fontVariant: ['tabular-nums'] },
  balLabel: { fontFamily: F.cond, fontSize: 13, letterSpacing: 1.8, textTransform: 'uppercase', color: C.text2, marginTop: 4 },
  evLine: { fontFamily: F.body, fontSize: 14, color: C.text2, minHeight: 20, marginTop: 4, textAlign: 'center' },
  pill: { flexDirection: 'row', alignItems: 'center', gap: 7, marginTop: 10, paddingVertical: 8, paddingHorizontal: 14, borderRadius: 999 },
  pillDot: { width: 7, height: 7, borderRadius: 4 },
  pillText: { fontFamily: F.bodySemi, fontSize: 14 },

  details: { marginTop: 12, padding: 16, borderRadius: 20, backgroundColor: C.card },
  dText: { fontFamily: F.body, fontSize: 15, lineHeight: 21, color: C.text2 },
  b: { fontFamily: F.bodySemi, color: C.text },
  dRow: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 10, marginTop: 10, borderTopWidth: 1, borderTopColor: C.line },
  dDay: { fontFamily: F.bodySemi, fontSize: 15, color: C.text },
  dWhy: { fontFamily: F.body, fontSize: 13, color: C.text2 },
  dFoot: { borderTopWidth: 1, borderTopColor: C.line, paddingTop: 10, marginTop: 2 },

  tiles: { flexDirection: 'row', gap: 8, marginTop: 22 },
  tile: { flex: 1, backgroundColor: C.card, borderRadius: 18, paddingVertical: 12, paddingHorizontal: 8, alignItems: 'center' },
  tileLabel: { fontFamily: F.cond, fontSize: 11, letterSpacing: 1.4, textTransform: 'uppercase', color: C.text2 },
  tileValue: { fontFamily: F.condBold, fontSize: 24, lineHeight: 28, color: C.text, marginTop: 6, fontVariant: ['tabular-nums'] },
  tileSub: { fontFamily: F.body, fontSize: 12, color: C.text2, marginTop: 2 },

  note: { flexDirection: 'row', alignItems: 'flex-start', gap: 12, padding: 14, borderRadius: 20, backgroundColor: C.card },
  noteTitle: { fontFamily: F.bodySemi, fontSize: 15, lineHeight: 20, color: C.text },
  noteSub: { fontFamily: F.body, fontSize: 13, color: C.text2, marginTop: 3 },
  x: { width: 30, height: 30, borderRadius: 15, backgroundColor: C.card2, alignItems: 'center', justifyContent: 'center' },
  manage: { fontFamily: F.bodySemi, fontSize: 13, color: C.text2, alignSelf: 'center' },

  card: { backgroundColor: C.card, borderRadius: 22, padding: 16 },
  whatIf: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 8, marginTop: 14 },
  whatIfLabel: { fontFamily: F.body, fontSize: 14, color: C.text2, marginRight: 2 },
  chip: { height: 34, paddingHorizontal: 14, borderRadius: 999, backgroundColor: C.card2, alignItems: 'center', justifyContent: 'center' },
  chipOn: { backgroundColor: '#fff' },
  chipText: { fontFamily: F.bodySemi, fontSize: 14, color: C.text },
  customBox: { flexDirection: 'row', gap: 2, paddingHorizontal: 12 },
  customInput: { width: 56, fontFamily: F.bodySemi, fontSize: 14, color: '#111', padding: 0, ...(Platform.OS === 'web' ? ({ outlineStyle: 'none' } as object) : {}) },

  cta: { height: 52, borderRadius: 999, backgroundColor: '#fff', alignItems: 'center', justifyContent: 'center' },
  ctaText: { fontFamily: F.bodySemi, fontSize: 17, color: '#111' },
  fixNote: { fontFamily: F.body, fontSize: 13, color: C.text2, marginTop: 10, textAlign: 'center' },
  done: { flexDirection: 'row', alignItems: 'center', gap: 12, marginTop: 16 },
  doneSub: { fontFamily: F.body, fontSize: 13, color: C.text2 },
  doneTitle: { fontFamily: F.bodySemi, fontSize: 17, color: C.text },
});

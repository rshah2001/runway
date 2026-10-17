// Spending — owner: an2thu. Month picker → where it went (one coloured bar per category) → every day
// (Tiger Data continuous aggregate) → subscriptions (GET /recurring) → the latest purchases.
// Visual spec: app/prototypes/today-v8.html (Spending tab).
import { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { Amount, Avatar, Fine, List, Row, SectionLabel } from '@/components/rw/list';
import { PageTitle, TopBar } from '@/components/rw/top-bar';
import { LoadState, Page, PressableScale, useWide } from '@/components/rw/ui';
import { C, F } from '@/constants/runway';
import { useLoad } from '@/hooks/use-load';
import { api } from '@/lib/api';
import { useStore } from '@/lib/store';
import { money, monthName, recentMonths, weekdayDate } from '@/lib/format';
import type { Recurring, Spending, SpendingCompare } from '@/lib/types';

/** One colour per category, biggest first — red, amber, blue, green, then quieter ones. */
const BAR = [C.red, C.amber, C.blue, C.green, '#a78bfa', '#2bb0c4', '#c2477a', C.slate];

export default function SpendingScreen() {
  const wide = useWide();
  const months = recentMonths(3);
  const [month, setMonth] = useState(months[months.length - 1]);
  const version = useStore().dataVersion; // money moved anywhere: re-fetch
  const sp = useLoad(() => api.spending(month), `${month}:${version}`);
  const subs = useLoad(() => api.recurring(), String(version));
  const isNow = month === months[months.length - 1];
  const d = sp.data;

  const picker = (
    <View style={s.seg} accessibilityRole="tablist">
      {months.map((m) => (
        <PressableScale key={m} onPress={() => setMonth(m)} style={[s.segBtn, m === month && s.segOn]} accessibilityRole="tab"
          accessibilityState={{ selected: m === month }}>
          <Text style={[s.segText, m === month && { color: C.text }]}>{monthName(m, 'short')}</Text>
        </PressableScale>
      ))}
    </View>
  );

  const left = d && (
    <>
      <SectionLabel>Where it went</SectionLabel>
      <List style={{ paddingVertical: 8 }}>
        {d.categories.length === 0 && <Text style={s.empty}>No purchases this month yet.</Text>}
        {d.categories.map((c, i) => (
          <View key={c.category} style={s.cat} accessible accessibilityLabel={`${c.category}: ${money(c.spent, 0)}`}>
            <View style={s.catTop}>
              <Text style={s.catName}>{c.category}</Text>
              <Delta change={d.compare?.categories.find((x) => x.category === c.category)?.change} />
              <Amount>{money(c.spent, 0)}</Amount>
            </View>
            <View style={s.track}>
              <View style={[s.fill, { width: `${Math.max(2, (c.spent / Math.max(1, d.categories[0].spent)) * 100)}%`, backgroundColor: BAR[i % BAR.length] }]} />
            </View>
          </View>
        ))}
      </List>
      <SectionLabel>Every day</SectionLabel>
      <Daily d={d} month={month} isNow={isNow} />
    </>
  );
  const right = d && (
    <>
      <Subscriptions subs={subs.data} />
      <SectionLabel>Latest</SectionLabel>
      <List>
        {d.transactions.length === 0 && <Row first title="No purchases this month." />}
        {d.transactions.slice(0, 8).map((t, i) => (
          <Row key={`${t.date}-${t.merchant}-${i}`} first={i === 0} left={<Avatar name={t.merchant} />} title={t.merchant}
            sub={`${t.category} · ${weekdayDate(t.date)}`} right={<Amount>{money(-t.amount, 2)}</Amount>} />
        ))}
      </List>
      <Fine>Transactions from Capital One Nessie.</Fine>
    </>
  );

  return (
    <Page onRefresh={() => { sp.reload(); subs.reload(); }} refreshing={sp.loading && !!sp.data}>
      <TopBar />
      <PageTitle title="Spending" sub={d ? `${isNow ? `${monthName(month)} so far` : monthName(month)} · ${money(d.total, 0)}` : monthName(month)} />
      {d?.compare && <VsLastMonth c={d.compare} />}
      {picker}
      {!d ? <View style={{ marginTop: 24 }}><LoadState error={sp.error} onRetry={sp.reload} /></View> : wide ? (
        <View style={s.wideRow}>
          <View style={{ flex: 1.3 }}>{left}</View>
          <View style={{ flex: 1 }}>{right}</View>
        </View>
      ) : <>{left}{right}</>}
    </Page>
  );
}

/** Spending per day across the whole month, so the axis is honest; today in white. */
function Daily({ d, month, isNow }: { d: Spending; month: string; isNow: boolean }) {
  const [y, m] = month.split('-').map(Number);
  const daysIn = new Date(y, m, 0).getDate();
  const lastDay = isNow ? new Date().getDate() : daysIn;
  const byDay = new Map(d.daily.map((x) => [Number(x.date.slice(8, 10)), x.spent]));
  const max = Math.max(1, ...d.daily.map((x) => x.spent));
  return (
    <List style={{ paddingVertical: 14 }}>
      <Text style={s.dailySub}>{d.transactions.length} purchases · about {money(d.total / Math.max(1, lastDay), 0)} a day</Text>
      <View style={s.bars} accessibilityLabel="Daily spending">
        {Array.from({ length: daysIn }, (_, i) => {
          const day = i + 1, v = byDay.get(day) ?? 0, future = day > lastDay, today = isNow && day === lastDay;
          return <View key={day} style={[s.bar, { height: future ? 4 : `${Math.max(4, (v / max) * 100)}%`,
            backgroundColor: future ? C.line : today ? '#fff' : C.slate, opacity: future || today ? 1 : 0.55 }]} />;
        })}
      </View>
      <View style={s.axis}>
        <Text style={s.axisText}>{monthName(month, 'short')} 1</Text>
        <Text style={s.axisText}>{monthName(month, 'short')} {daysIn}</Text>
      </View>
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
  const [text, tone] = Math.abs(c.change) < 1 ? [`About the same as ${span}`, C.text2]
    : c.change < 0 ? [`${amount} less than ${span}`, C.green]
    : [`${amount} more than ${span}`, C.amber];
  return <Text style={[s.vs, { color: tone }]} accessibilityLabel={`Compared with last month: ${text}`}>{text}</Text>;
}

/** A category's change against the same days last month: "−$30" (less) or "+$18" (more). */
function Delta({ change }: { change?: number }) {
  if (change === undefined || Math.abs(change) < 1) return null;
  const less = change < 0;
  return (
    <Text style={[s.delta, { color: less ? C.green : C.amber }]} accessibilityLabel={`${money(Math.abs(change), 0)} ${less ? 'less' : 'more'} than last month`}>
      {`${less ? '−' : '+'}${money(Math.abs(change), 0)}`}
    </Text>
  );
}

const s = StyleSheet.create({
  vs: { fontFamily: F.bodySemi, fontSize: 15, marginTop: -4, marginBottom: 14 },
  delta: { fontFamily: F.condBold, fontSize: 14, marginLeft: 'auto', marginRight: 10 },
  wideRow: { flexDirection: 'row', gap: 24, alignItems: 'flex-start' },
  seg: { flexDirection: 'row', marginTop: 18, padding: 3, borderRadius: 999, backgroundColor: C.card },
  segBtn: { flex: 1, height: 32, borderRadius: 999, alignItems: 'center', justifyContent: 'center' },
  segOn: { backgroundColor: C.card2 },
  segText: { fontFamily: F.cond, fontSize: 14, letterSpacing: 1.6, textTransform: 'uppercase', color: C.text2 },
  empty: { fontFamily: F.body, fontSize: 15, color: C.text2, paddingVertical: 10 },
  cat: { paddingVertical: 8 },
  catTop: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  catName: { fontFamily: F.bodySemi, fontSize: 16, color: C.text },
  track: { height: 8, borderRadius: 4, backgroundColor: C.card2, marginTop: 6, overflow: 'hidden' },
  fill: { height: '100%', borderRadius: 4 },
  dailySub: { fontFamily: F.body, fontSize: 14, color: C.text2 },
  bars: { flexDirection: 'row', alignItems: 'flex-end', gap: 3, height: 72, marginTop: 14 },
  bar: { flex: 1, borderRadius: 2, minHeight: 2 },
  axis: { flexDirection: 'row', justifyContent: 'space-between', marginTop: 6 },
  axisText: { fontFamily: F.body, fontSize: 12, color: C.text3 },
});

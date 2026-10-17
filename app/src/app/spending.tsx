// Spending — owner: an2thu. Month picker, total + daily bars (Tiger Data continuous aggregate),
// categories, subscriptions (GET /recurring) and the latest transactions.
import { useState } from 'react';
import { StyleSheet, View } from 'react-native';

import { ActRow } from '@/components/rw/rows';
import { Caps, Card, CardHeader, LoadState, Num, Page, PressableScale, SectionTitle, T, useWide } from '@/components/rw/ui';
import { C, F } from '@/constants/runway';
import { useLoad } from '@/hooks/use-load';
import { api } from '@/lib/api';
import { money, monthName, recentMonths, weekdayDate } from '@/lib/format';
import type { Recurring, Spending } from '@/lib/types';

export default function SpendingScreen() {
  const wide = useWide();
  const months = recentMonths(3);
  const [month, setMonth] = useState(months[months.length - 1]);
  const sp = useLoad(() => api.spending(month), month);
  const subs = useLoad(() => api.recurring());
  const isNow = month === months[months.length - 1];

  const picker = (
    <View style={s.seg} accessibilityRole="tablist">
      {months.map((m) => (
        <PressableScale key={m} onPress={() => setMonth(m)} style={[s.segBtn, m === month && s.segOn]} accessibilityRole="tab"
          accessibilityState={{ selected: m === month }}>
          <Caps tone={m === month ? 'default' : 'dim'} size={14} style={{ letterSpacing: 1.8 }}>{monthName(m, 'short')}</Caps>
        </PressableScale>
      ))}
    </View>
  );

  const d = sp.data;
  const body = !d ? <LoadState error={sp.error} onRetry={sp.reload} /> : (
    <>
      {wide ? (
        <View style={s.wideRow}>
          <View style={{ flex: 1.3 }}><TotalCard d={d} month={month} isNow={isNow} /></View>
          <View style={{ flex: 1, gap: 8 }}><SubsCard subs={subs.data} grow={false} /><TopCard d={d} grow={false} /></View>
        </View>
      ) : <TotalCard d={d} month={month} isNow={isNow} />}
      <View style={wide ? [s.wideRow, { alignItems: 'flex-start' }] : undefined}>
        <View style={wide ? { flex: 1.3 } : undefined}>
          <SectionTitle>Categories</SectionTitle>
          <Card style={s.block}>
            <CardHeader title="Where it went" chevron />
            <View style={{ gap: 8, marginTop: 12 }}>
              {d.categories.map((c) => (
                <ActRow key={c.category} kind={c.category} amount={money(c.spent, 0)} title={c.category}
                  subtitle={`${c.purchases} purchase${c.purchases === 1 ? '' : 's'}`}
                  rightTop={d.total ? `${Math.round((c.spent / d.total) * 100)}%` : '—'} rightBottom="of total" />
              ))}
              {d.categories.length === 0 && <T tone="dim">No purchases this month yet.</T>}
            </View>
          </Card>
        </View>
        <View style={wide ? { flex: 1 } : undefined}>
          {!wide && <View style={[s.pair, { marginTop: 14 }]}><SubsCard subs={subs.data} /><TopCard d={d} /></View>}
          <SectionTitle>Latest transactions</SectionTitle>
          <Card style={s.block}>
            {d.transactions.slice(0, 8).map((t, i) => (
              <View key={`${t.date}-${t.merchant}-${i}`} style={[s.tx, i > 0 && { borderTopWidth: 1, borderTopColor: C.line }]}>
                <View style={s.mono}><Caps tone="dim" size={17}>{t.merchant[0]}</Caps></View>
                <View style={{ flex: 1, minWidth: 0 }}>
                  <T style={{ fontFamily: F.bodySemi }} numberOfLines={1}>{t.merchant}</T>
                  <T tone="dim" style={{ fontSize: 13 }} numberOfLines={1}>{t.category} · {weekdayDate(t.date)}</T>
                </View>
                <Caps size={17} style={{ letterSpacing: 0.5 }}>{money(-t.amount)}</Caps>
              </View>
            ))}
            {d.transactions.length === 0 && <T tone="dim">No transactions this month.</T>}
          </Card>
        </View>
      </View>
      <View style={s.credit}><View style={s.dot} /><Caps tone="faint" size={12}>Transactions from Capital One Nessie</Caps></View>
    </>
  );

  return (
    <Page onRefresh={() => { sp.reload(); subs.reload(); }} refreshing={sp.loading && !!sp.data}>
      <View style={s.head}>
        <Caps size={34} style={{ letterSpacing: 0.4, textTransform: 'none' }}>Spending</Caps>
        <T tone="dim">{isNow ? `${monthName(month)} so far` : monthName(month)}</T>
      </View>
      {picker}
      {body}
    </Page>
  );
}

function TotalCard({ d, month, isNow }: { d: Spending; month: string; isNow: boolean }) {
  // The API returns one row per day with spending; lay them on the full month so the axis is honest.
  const [y, m] = month.split('-').map(Number);
  const daysIn = new Date(y, m, 0).getDate();
  const today = new Date();
  const lastDay = isNow ? today.getDate() : daysIn;
  const byDay = new Map(d.daily.map((x) => [Number(x.date.slice(8, 10)), x.spent]));
  const max = Math.max(1, ...d.daily.map((x) => x.spent));
  return (
    <Card style={{ marginTop: 12 }}>
      <CardHeader title="Total spent" />
      <Num size={46} style={{ marginTop: 12 }}>{money(d.total)}</Num>
      <T tone="dim" style={{ fontSize: 14, marginTop: 2 }}>
        {d.transactions.length} purchases · about {money(d.total / Math.max(1, lastDay), 0)} a day
      </T>
      <View style={s.bars} accessibilityLabel="Daily spending">
        {Array.from({ length: daysIn }, (_, i) => {
          const day = i + 1, v = byDay.get(day) ?? 0, future = day > lastDay;
          return <View key={day} style={[s.bar, { height: future ? 4 : `${Math.max(4, (v / max) * 100)}%`,
            backgroundColor: future ? C.line : isNow && day === lastDay ? '#fff' : C.slate, opacity: future || (isNow && day === lastDay) ? 1 : 0.55 }]} />;
        })}
      </View>
      <View style={s.axis}><Caps tone="faint" size={11}>{monthName(month, 'short')} 1</Caps><Caps tone="faint" size={11}>{monthName(month, 'short')} {daysIn}</Caps></View>
    </Card>
  );
}

/** `grow`: share a row's width (phone pair). In the desktop column the card takes its natural height. */
function SubsCard({ subs, grow = true }: { subs: Recurring[] | null; grow?: boolean }) {
  // Normalise each charge to a 30-day month, as the backend's interval_days describes it.
  const monthly = (subs ?? []).reduce((t, r) => t + r.amount * (30 / r.interval_days), 0);
  return (
    <Card style={grow ? { flex: 1 } : undefined}>
      <CardHeader title="Subscriptions" chevron />
      <Num size={30} style={{ marginTop: 12 }}>{subs ? money(monthly) : '—'}</Num>
      <T tone="dim" style={{ fontSize: 13 }}>per month · {money(monthly * 12, 0)}/yr</T>
      <View style={{ marginTop: 10, gap: 4 }}>
        {(subs ?? []).map((r) => (
          <View key={r.merchant} style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
            <T tone="dim" style={{ fontSize: 13 }}>{r.merchant}</T><T tone="dim" style={{ fontSize: 13 }}>{money(r.amount)}</T>
          </View>
        ))}
      </View>
    </Card>
  );
}

function TopCard({ d, grow = true }: { d: Spending; grow?: boolean }) {
  const top = d.categories[0];
  return (
    <Card style={grow ? { flex: 1 } : undefined}>
      <CardHeader title="Top category" chevron />
      <Num size={30} style={{ marginTop: 12 }}>{top?.category ?? '—'}</Num>
      <T tone="dim" style={{ fontSize: 13 }}>{top && d.total ? `${Math.round((top.spent / d.total) * 100)}% of spending` : 'No spending yet'}</T>
    </Card>
  );
}

const s = StyleSheet.create({
  head: { paddingHorizontal: 4 },
  seg: { flexDirection: 'row', marginTop: 14, padding: 3, borderRadius: 999, backgroundColor: C.card },
  segBtn: { flex: 1, height: 32, borderRadius: 999, alignItems: 'center', justifyContent: 'center' },
  segOn: { backgroundColor: C.card2 },
  block: { paddingHorizontal: 12, paddingTop: 14, paddingBottom: 12 },
  pair: { flexDirection: 'row', gap: 8 },
  wideRow: { flexDirection: 'row', gap: 24 },
  bars: { flexDirection: 'row', alignItems: 'flex-end', gap: 3, height: 72, marginTop: 16 },
  bar: { flex: 1, borderRadius: 2, minHeight: 2 },
  axis: { flexDirection: 'row', justifyContent: 'space-between', marginTop: 6 },
  tx: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 10, paddingHorizontal: 4 },
  mono: { width: 40, height: 40, borderRadius: 8, backgroundColor: C.line, alignItems: 'center', justifyContent: 'center' },
  credit: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, paddingTop: 22 },
  dot: { width: 6, height: 6, borderRadius: 3, backgroundColor: C.green },
});

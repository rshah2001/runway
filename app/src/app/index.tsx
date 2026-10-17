// Today — owner: an2thu. Rings → status cards → the runway (with the takeoff) → upcoming bills and pay.
// Visual spec: app/prototypes/runway.html.
import { useRouter, useIsFocused } from 'expo-router';
import { useEffect, useState } from 'react';
import { StyleSheet, View } from 'react-native';

import { AccountButton } from '@/components/login/account-button';
import { ApprovalCard } from '@/components/rw/approval-card';
import { Swoosh } from '@/components/rw/icons';
import { Ring } from '@/components/rw/ring';
import { ActRow } from '@/components/rw/rows';
import { RunwayStrip } from '@/components/rw/runway-strip';
import { Badge, Btn, Card, CardHeader, Caps, LoadState, Page, SectionTitle, T, useWide } from '@/components/rw/ui';
import { C } from '@/constants/runway';
import { useLoad } from '@/hooks/use-load';
import { api } from '@/lib/api';
import { money, monthDay, weekday } from '@/lib/format';
import { dipCount, isClear, runwayDays, safeToSpend, upcoming, withApprovedTransfer } from '@/lib/runway';
import { setStore, useStore } from '@/lib/store';
import type { Account, Forecast, PendingAction } from '@/lib/types';

const KIND_LABEL: Record<string, string> = { bill: 'Bill', subscription: 'Subscription', card_payment: 'Card payment', paycheck: 'Paycheck', transfer: 'Transfer' };

export default function TodayScreen() {
  const wide = useWide();
  const router = useRouter();
  const focused = useIsFocused();
  const store = useStore();
  const forecast = useLoad(() => api.forecast(30));
  const me = useLoad(() => api.me());

  // What the screen shows lags the store until Today is on screen, so an approval made on Ask
  // plays its takeoff here instead of finishing invisibly in the background.
  // (React's "adjust state when an input changes" pattern: compared during render, no effect.)
  // The pre-approval lowest balance and savings are remembered so we can tell whether the backend
  // already reflects the transfer when we re-fetch (see `overlay` below).
  const [shown, setShown] = useState({ amount: store.approvedAmount, takeoffKey: 0, baseLow: NaN, baseSavings: NaN });
  if (focused && shown.amount !== store.approvedAmount) {
    setShown({
      amount: store.approvedAmount,
      takeoffKey: shown.takeoffKey + (store.celebrate ? 1 : 0),
      baseLow: forecast.data?.low.balance ?? NaN,
      baseSavings: me.data?.accounts.find((a) => a.type === 'Savings')?.balance ?? NaN,
    });
  }
  const takeoffKey = shown.takeoffKey;
  // After an approval: clear the shared flag (an external store) and re-fetch the real numbers.
  useEffect(() => {
    if (takeoffKey === 0) return;
    setStore({ celebrate: false });
    forecast.reload();
    me.reload();
    // reload functions are stable; only a new takeoff should trigger this
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [takeoffKey]);

  if (!forecast.data) return <Page><LoadState error={forecast.error} onRetry={forecast.reload} /></Page>;

  // TODO(engine): while transfers aren't live, the backend's numbers don't change after an approval,
  // so the app shows the move itself. Once they're live the re-fetched numbers differ from the
  // pre-approval ones and the backend's values are shown as-is — never counted twice.
  const savingsAccount = me.data?.accounts.find((a) => a.type === 'Savings');
  const overlay = forecast.data.low.balance === shown.baseLow ? shown.amount : 0;
  const movedFromSavings = savingsAccount?.balance === shown.baseSavings ? shown.amount : 0;
  const f = withApprovedTransfer(forecast.data, overlay);

  const rings = <RingsRow f={f} savings={savingsAccount} moved={movedFromSavings} />;
  const status = (
    <View style={[s.pair, wide && { flexDirection: 'column' }]}>
      <ForecastCard f={f} />
      <SpendCard f={f} />
    </View>
  );
  const runway = <RunwayCard f={f} takeoffKey={takeoffKey} onAsk={() => router.navigate('/ask')} />;
  const coming = (
    <Card style={s.block}>
      <CardHeader title="Bills & pay · next 2 weeks" chevron />
      <View style={{ gap: 8, marginTop: 12 }}>
        {upcoming(f).map((e, i) => (
          <ActRow key={`${e.date}-${e.label}-${i}`} kind={e.kind} amount={`${e.amount > 0 ? '+' : '−'}${money(Math.abs(e.amount), 0)}`}
            title={e.label} subtitle={KIND_LABEL[e.kind]} rightTop={weekday(e.date)} rightBottom={monthDay(e.date)} />
        ))}
        {upcoming(f).length === 0 && <T tone="dim">Nothing scheduled in the next two weeks.</T>}
      </View>
    </Card>
  );

  return (
    <Page onRefresh={() => { forecast.reload(); me.reload(); }} refreshing={forecast.loading && !!forecast.data}>
      {!wide && (
        <View style={s.top}>
          <AccountButton />
          <View style={s.day}><Caps tone="dim" size={14}>‹</Caps><Caps size={14} style={{ letterSpacing: 2 }}>Today</Caps><Caps tone="dim" size={14}>›</Caps></View>
          <View style={s.circ}><Caps size={15}>···</Caps></View>
        </View>
      )}
      {!wide && <View style={s.wordmark}><Swoosh /><Caps size={22} style={{ letterSpacing: 9, fontFamily: 'BarlowCondensed_500Medium' }}>Runway</Caps></View>}

      {wide ? (
        <>
          <View style={s.wideRow}><View style={{ flex: 1.4 }}>{rings}</View><View style={{ flex: 1 }}>{status}</View></View>
          <View style={[s.wideRow, { alignItems: 'flex-start' }]}>
            <View style={{ flex: 1.4 }}><SectionTitle>My Runway</SectionTitle>{runway}</View>
            <View style={{ flex: 1 }}><SectionTitle>Upcoming</SectionTitle>{coming}</View>
          </View>
        </>
      ) : (
        <>
          {rings}
          {status}
          <SectionTitle>My Runway</SectionTitle>
          {runway}
          <SectionTitle>Upcoming</SectionTitle>
          {coming}
        </>
      )}
      <View style={s.credit}><View style={s.dot} /><Caps tone="faint" size={12}>Balances from Capital One Nessie</Caps></View>
    </Page>
  );
}

function RingsRow({ f, savings, moved }: { f: Forecast; savings?: Account; moved: number }) {
  const days = runwayDays(f), horizon = f.points.length - 1;
  // Savings goal: three months of the biggest bill (rent) — a common emergency-fund rule of thumb.
  const rent = Math.max(0, ...f.events.filter((e) => e.kind === 'bill').map((e) => -e.amount));
  const goal = rent ? rent * 3 : 1500;
  const sav = (savings?.balance ?? 0) - moved; // TODO(engine): drop "- moved" once balances reflect transfers
  return (
    <View style={s.rings}>
      <Ring label="Runway" value={days >= horizon ? `${horizon}+` : String(days)} unit="days" frac={days / horizon}
        color={days >= horizon ? C.green : days < 7 ? C.red : C.amber} />
      <Ring label="Lowest" value={money(f.low.balance, 0)} unit={monthDay(f.low.date)} frac={f.low.balance / f.safe_floor}
        color={f.low.balance < f.safe_floor ? C.red : C.green} />
      <Ring label="Savings" value={savings ? money(sav, 0) : '—'} unit={`of ${money(goal, 0)}`} frac={sav / goal} color={C.blue} />
    </View>
  );
}

function ForecastCard({ f }: { f: Forecast }) {
  const n = dipCount(f);
  return (
    <Card style={{ flex: 1 }}>
      <CardHeader title="Forecast" chevron />
      <View style={s.metric}>
        <Badge tone={n ? 'red' : 'green'}>{n ? '!' : '✓'}</Badge>
        <View style={{ flex: 1 }}>
          <Caps tone={n ? 'red' : 'green'}>{n ? 'Below floor' : 'Within range'}</Caps>
          <T tone="dim" style={{ fontSize: 14 }}>{n} dip{n === 1 ? '' : 's'} · next 30 days</T>
        </View>
      </View>
    </Card>
  );
}

function SpendCard({ f }: { f: Forecast }) {
  const v = safeToSpend(f);
  return (
    <Card style={{ flex: 1 }}>
      <CardHeader title="Safe to spend" chevron />
      <View style={s.metric}>
        <Badge tone={v ? 'green' : 'amber'}>{money(v, 0)}</Badge>
        <View style={{ flex: 1 }}>
          <Caps tone={v ? 'green' : 'amber'}>{v ? 'Available' : 'Nothing spare'}</Caps>
          <T tone="dim" style={{ fontSize: 14 }}>After bills + floor</T>
        </View>
      </View>
    </Card>
  );
}

/** The runway plus the fix: the agent proposes a transfer, the user approves it here. */
function RunwayCard({ f, takeoffKey, onAsk }: { f: Forecast; takeoffKey: number; onAsk: () => void }) {
  const days = runwayDays(f), horizon = f.points.length - 1, clear = isClear(f);
  const [proposal, setProposal] = useState<PendingAction | null>(null);
  const [asking, setAsking] = useState(false);
  const [askError, setAskError] = useState(false);

  async function getFix() {
    setAsking(true);
    setAskError(false);
    try {
      const r = await api.chat('Fix it');
      setProposal(r.pending_action);
      if (!r.pending_action) setAskError(true);
    } catch {
      setAskError(true);
    } finally {
      setAsking(false);
    }
  }

  return (
    <Card style={s.block}>
      <CardHeader title="Checking · next 30 days"
        right={<Caps tone={clear ? 'green' : 'red'}>{clear ? `Clear · ${horizon}+ days` : `${days} days left`}</Caps>} />
      <View style={{ marginTop: 6, marginBottom: 4 }}>
        <RunwayStrip days={days} horizon={horizon} endLabel={days < horizon ? monthDay(f.points[days].date) : ''}
          lastLabel={monthDay(f.points[horizon].date)} takeoffKey={takeoffKey} />
      </View>
      {proposal ? (
        <ApprovalCard action={proposal} compact />
      ) : (
        <View style={s.fix}>
          <View style={{ flex: 1 }}>
            <Caps size={16}>{clear ? "You're covered" : 'Cover the dip'}</Caps>
            <T tone="dim" style={{ fontSize: 13 }}>
              {clear ? `Checking stays above ${money(f.safe_floor, 0)} all month.` : askError
                ? "Couldn't get a suggestion. Try again, or ask on the Ask tab."
                : `Runway's agent proposes a transfer — you approve it.`}
            </T>
          </View>
          {clear ? <Btn label="Ask" ghost onPress={onAsk} /> : <Btn label={asking ? 'Thinking…' : 'Fix it'} disabled={asking} onPress={getFix} />}
        </View>
      )}
    </Card>
  );
}

const s = StyleSheet.create({
  top: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 8 },
  circ: { width: 36, height: 36, borderRadius: 18, backgroundColor: C.card2, alignItems: 'center', justifyContent: 'center' },
  day: { flexDirection: 'row', alignItems: 'center', gap: 14, height: 32, paddingHorizontal: 14, borderRadius: 999, backgroundColor: C.card },
  wordmark: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, marginTop: 14 },
  rings: { flexDirection: 'row', paddingTop: 18, paddingHorizontal: 2, gap: 4 },
  pair: { flexDirection: 'row', gap: 8, marginTop: 14 },
  metric: { flexDirection: 'row', alignItems: 'center', gap: 10, marginTop: 16 },
  block: { paddingHorizontal: 12, paddingTop: 14, paddingBottom: 12 },
  fix: { flexDirection: 'row', alignItems: 'center', gap: 12, marginTop: 10, padding: 12, borderRadius: 10, backgroundColor: C.card2 },
  wideRow: { flexDirection: 'row', gap: 24, alignItems: 'center' },
  credit: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, paddingTop: 22 },
  dot: { width: 6, height: 6, borderRadius: 3, backgroundColor: C.green },
});

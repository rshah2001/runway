// Today — owner: an2thu. Rings (runway · safe to spend · payday) → forecast + lowest point → the runway
// (with the takeoff) → upcoming bills and pay. Chat opens from the floating button (components/rw/chat.tsx).
// Visual spec: app/prototypes/runway.html.
import { useIsFocused, useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { RefreshControl, StyleSheet, useWindowDimensions, View } from 'react-native';
import Animated, { useAnimatedScrollHandler, useSharedValue } from 'react-native-reanimated';

import { AccountButton } from '@/components/login/account-button';
import { ApprovalCard } from '@/components/rw/approval-card';
import { openChat } from '@/components/rw/chat';
import { Swoosh } from '@/components/rw/icons';
import { Ring } from '@/components/rw/ring';
import { ActRow } from '@/components/rw/rows';
import { RunwayStrip } from '@/components/rw/runway-strip';
import { Glows, TodayInteractive } from '@/components/today/today-interactive';
import { OptionA, OptionB } from '@/components/today/today-options';
import { Btn, Card, CardHeader, Caps, LoadState, Page, SectionTitle, T, useWide } from '@/components/rw/ui';
import { C, MAX_WIDTH } from '@/constants/runway';
import { useLoad } from '@/hooks/use-load';
import { api } from '@/lib/api';
import { money, monthDay, weekday, weekdayDate } from '@/lib/format';
import { daysFromToday, isClear, nextPaycheck, payCycleDays, runwayDays, safeToSpend, upcoming, withApprovedTransfer } from '@/lib/runway';
import { setStore, useStore } from '@/lib/store';
import type { Forecast, PendingAction } from '@/lib/types';

const KIND_LABEL: Record<string, string> = { bill: 'Bill', subscription: 'Subscription', card_payment: 'Card payment', paycheck: 'Paycheck', transfer: 'Transfer' };

export default function TodayScreen() {
  const wide = useWide();
  const focused = useIsFocused();
  const { v: param } = useLocalSearchParams<{ v?: string }>();
  // the interactive Today is the default; ?v=classic keeps the old rings screen, ?v=b / ?v=compare the runway option
  const v = param ?? 'a';
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
  const overlay = forecast.data.low.balance === shown.baseLow ? shown.amount : 0;
  const f = withApprovedTransfer(forecast.data, overlay);

  if (v === 'a') {
    return <InteractiveToday f={f} name={me.data?.first_name} refreshing={forecast.loading} onRefresh={() => { forecast.reload(); me.reload(); }} />;
  }
  if (v === 'b' || v === 'compare') {
    const both = v === 'compare';
    return (
      <Page onRefresh={() => { forecast.reload(); me.reload(); }} refreshing={forecast.loading && !!forecast.data}>
        {!wide && (
          <View style={s.top}>
            <View style={s.brand}><Swoosh /><Caps size={20} style={{ letterSpacing: 7, fontFamily: 'BarlowCondensed_500Medium' }}>Runway</Caps></View>
            <AccountButton />
          </View>
        )}
        <T style={s.hello}>{`Hi ${me.data?.first_name ?? 'there'}`}</T>
        <View style={both && wide ? s.compare : { gap: 28 }}>
          {both && (
            <View style={both && wide ? { flex: 1 } : undefined}>
              {both && <T tone="dim" style={s.optionLabel}>Option A · the balance line</T>}
              <OptionA f={f} compact={both} />
            </View>
          )}
          {(v === 'b' || both) && (
            <View style={both && wide ? { flex: 1 } : undefined}>
              {both && <T tone="dim" style={s.optionLabel}>Option B · the runway</T>}
              <OptionB f={f} takeoffKey={takeoffKey} compact={both} />
            </View>
          )}
        </View>
        <View style={s.credit}><View style={s.dot} /><T tone="faint" style={{ fontSize: 13 }}>Balances from Capital One Nessie</T></View>
      </Page>
    );
  }

  const rings = <RingsRow f={f} />;
  const low = <LowLine f={f} />;
  const runway = <RunwayCard f={f} takeoffKey={takeoffKey} />;
  const coming = (
    <Card style={s.block}>
      <CardHeader title="Next 2 weeks" />
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
          <View style={s.brand}><Swoosh /><Caps size={20} style={{ letterSpacing: 7, fontFamily: 'BarlowCondensed_500Medium' }}>Runway</Caps></View>
          <AccountButton />
        </View>
      )}

      {wide ? (
        <>
          <View style={{ maxWidth: 640, width: '100%', alignSelf: 'center' }}>{rings}{low}</View>
          <View style={[s.wideRow, { alignItems: 'flex-start' }]}>
            <View style={{ flex: 1.4 }}><SectionTitle>My Runway</SectionTitle>{runway}</View>
            <View style={{ flex: 1 }}><SectionTitle>Upcoming</SectionTitle>{coming}</View>
          </View>
        </>
      ) : (
        <>
          {rings}
          {low}
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

/** Option A, interactive (components/today/today-interactive.tsx), in a scroll view that drives its 3D reveals. */
function InteractiveToday({ f, name, refreshing, onRefresh }: { f: Forecast; name?: string; refreshing: boolean; onRefresh: () => void }) {
  const wide = useWide();
  const { height } = useWindowDimensions();
  const scrollY = useSharedValue(0);
  const onScroll = useAnimatedScrollHandler((e) => { scrollY.set(e.contentOffset.y); });
  return (
    <Page scroll={false} backdrop={<Glows />}>
      <Animated.ScrollView onScroll={onScroll} scrollEventThrottle={16} contentContainerStyle={{ paddingBottom: 40 }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={C.text2} />}>
        {!wide && (
          <View style={s.top}>
            <View style={s.brand}><Swoosh /><Caps size={20} style={{ letterSpacing: 7, fontFamily: 'BarlowCondensed_500Medium' }}>Runway</Caps></View>
            <AccountButton />
          </View>
        )}
        <TodayInteractive f={f} name={name} wide={wide} scrollY={scrollY} viewport={height} />
        <View style={s.credit}><View style={s.dot} /><T tone="faint" style={{ fontSize: 13 }}>Balances from Capital One Nessie</T></View>
      </Animated.ScrollView>
    </Page>
  );
}

/**
 * Three questions, one ring each — every value read straight off the forecast:
 *  - Runway: days until checking first falls under the floor (ring = share of the 30 days covered).
 *  - Safe to spend: what's free today without breaking the floor (ring = share of today's balance).
 *  - Payday: days until the next paycheck (ring fills as payday gets closer within the pay cycle).
 */
function RingsRow({ f }: { f: Forecast }) {
  const wide = useWide();
  const { width } = useWindowDimensions();
  // Three rings must fit side by side on the narrowest phone: page padding 24, gaps 8.
  const size = wide ? 116 : Math.max(84, Math.min(108, Math.floor((Math.min(width, MAX_WIDTH) - 24 - 8) / 3) - 4));
  const days = runwayDays(f), horizon = f.points.length - 1, clear = days >= horizon;
  const safe = safeToSpend(f), todayBalance = f.points[0].balance;
  const pay = nextPaycheck(f), cycle = payCycleDays(f), until = pay ? daysFromToday(f, pay.date) : null;
  return (
    <View style={[s.rings, { gap: wide ? 16 : 4 }]}>
      <Ring size={size} label="Runway" value={clear ? `${horizon}+` : String(days)} unit="days" frac={days / horizon}
        color={clear ? C.green : days < 7 ? C.red : C.amber}
        caption={clear ? "you're covered" : 'until money runs low'} />
      <Ring size={size} label="Safe to spend" value={money(safe, 0)} unit="today" frac={todayBalance > 0 ? safe / todayBalance : 0}
        color={safe > 0 ? C.green : C.amber} caption={safe > 0 ? 'free after bills' : 'nothing spare yet'} />
      <Ring size={size} label="Payday" value={until === null ? '—' : String(until)} unit={until === 1 ? 'day' : 'days'}
        frac={until === null ? 0 : 1 - until / cycle} color={C.blue}
        caption={pay ? `${money(pay.amount, 0)} on ${weekday(pay.date)}` : 'none in 30 days'} />
    </View>
  );
}

/**
 * The tightest day in one plain sentence (it replaced the Forecast and Lowest point cards).
 * "Cushion" = the safety floor: the money we keep in checking for surprises.
 */
function LowLine({ f }: { f: Forecast }) {
  const gap = f.low.balance - f.safe_floor;
  return (
    <View style={s.lowLine} accessible>
      <View style={[s.lowDot, { backgroundColor: gap < 0 ? C.red : C.green }]} />
      <T style={{ flex: 1, fontSize: 15 }}>
        Lowest: <T style={{ fontFamily: 'Barlow_600SemiBold', color: gap < 0 ? C.red : C.green }}>{money(f.low.balance, 0)}</T> on {weekdayDate(f.low.date)}
        <T tone="dim">{gap < 0 ? ` · ${money(-gap, 0)} below your ${money(f.safe_floor, 0)} cushion` : ` · above your ${money(f.safe_floor, 0)} cushion`}</T>
      </T>
    </View>
  );
}

/** The runway plus the fix: the agent proposes a transfer, the user approves it here. */
function RunwayCard({ f, takeoffKey }: { f: Forecast; takeoffKey: number }) {
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
      <CardHeader title="Next 30 days"
        right={<Caps tone={clear ? 'green' : 'red'}>{clear ? 'All month' : `${days} days left`}</Caps>} />
      <View style={{ marginTop: 6, marginBottom: 4 }}>
        <RunwayStrip days={days} horizon={horizon} endLabel={days < horizon ? monthDay(f.points[days].date) : ''}
          lastLabel={monthDay(f.points[horizon].date)} takeoffKey={takeoffKey} />
      </View>
      {proposal ? (
        <ApprovalCard action={proposal} compact />
      ) : (
        <View style={s.fix}>
          <View style={{ flex: 1 }}>
            <Caps size={16}>{clear ? "You're covered" : `Money runs low on ${monthDay(f.points[days].date)}`}</Caps>
            <T tone="dim" style={{ fontSize: 13 }}>
              {clear ? `Your money stays above your ${money(f.safe_floor, 0)} cushion all month.` : askError
                ? "Couldn't get a suggestion. Try again, or ask in the chat."
                : 'Runway can suggest a quick fix. Nothing moves until you say yes.'}
            </T>
          </View>
          {clear ? <Btn label="Ask" ghost onPress={openChat} /> : <Btn label={asking ? 'Thinking…' : 'Fix it'} disabled={asking} onPress={getFix} />}
        </View>
      )}
    </Card>
  );
}

const s = StyleSheet.create({
  top: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 4, paddingTop: 4 },
  brand: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  lowLine: { flexDirection: 'row', alignItems: 'center', gap: 10, marginTop: 16, paddingVertical: 12, paddingHorizontal: 14, borderRadius: 14, backgroundColor: C.card },
  lowDot: { width: 8, height: 8, borderRadius: 4 },
  rings: { flexDirection: 'row', paddingTop: 18, alignItems: 'flex-start' },
  block: { paddingHorizontal: 12, paddingTop: 14, paddingBottom: 12 },
  fix: { flexDirection: 'row', alignItems: 'center', gap: 12, marginTop: 10, padding: 12, borderRadius: 10, backgroundColor: C.card2 },
  wideRow: { flexDirection: 'row', gap: 24, alignItems: 'center' },
  hello: { fontFamily: 'Barlow_600SemiBold', fontSize: 22, marginTop: 18, marginBottom: 14 },
  compare: { flexDirection: 'row', gap: 24, alignItems: 'flex-start' },
  optionLabel: { fontSize: 14, marginBottom: 8 },
  credit: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, paddingTop: 22 },
  dot: { width: 6, height: 6, borderRadius: 3, backgroundColor: C.green },
});

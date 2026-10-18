// Activity — every support transfer and repayment that involves you, newest first, each with a plain
// "why" written from your side only (GET /activity, backend/app/activity.py). Tap an entry to see why it
// happened and the bank reference for your side of the transfer.
import { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { Icon } from '@/components/rw/icons';
import { Amount, Avatar, Fine, List, Row } from '@/components/rw/list';
import { PageTitle, TopBar } from '@/components/rw/top-bar';
import { LoadState, Page, PressableScale } from '@/components/rw/ui';
import { C, F } from '@/constants/runway';
import { useLoad } from '@/hooks/use-load';
import { api } from '@/lib/api';
import { money, monthDay } from '@/lib/format';
import { moneyMoved, useStore } from '@/lib/store';
import type { ActivityItem } from '@/lib/types';

type Filter = 'all' | 'received' | 'given' | 'repayments' | 'waiting';
const FILTERS: [Filter, string][] = [['all', 'All'], ['received', 'Received'], ['given', 'Sent'], ['repayments', 'Repaid'], ['waiting', 'Waiting']];
const IN_FILTER: Record<Filter, ActivityItem['kind'][]> = {
  all: ['received', 'provided', 'repaid_by_me', 'repaid_to_me', 'waiting', 'pending_my_ok', 'problem', 'sent', 'got', 'asked', 'asked_you'],
  received: ['received', 'got'],
  given: ['provided', 'sent'],
  repayments: ['repaid_by_me', 'repaid_to_me'],
  waiting: ['waiting', 'pending_my_ok', 'problem', 'asked', 'asked_you'],
};
const LOOK: Record<ActivityItem['kind'], [string, string]> = {
  received: ['shield', C.green],
  provided: ['shield', C.cover],
  repaid_by_me: ['check', C.green],
  repaid_to_me: ['check', C.green],
  waiting: ['transfer', C.amber],
  pending_my_ok: ['transfer', C.amber],
  problem: ['close', C.text2],
  sent: ['send', C.cover],
  got: ['send', C.green],
  asked: ['transfer', C.amber],
  asked_you: ['transfer', C.amber],
};

export default function ActivityScreen() {
  const version = String(useStore().dataVersion);
  const feed = useLoad(() => api.activity(), version);
  const [filter, setFilter] = useState<Filter>('all');
  const [open, setOpen] = useState<string | null>(null);
  const items = (feed.data ?? []).filter((x) => IN_FILTER[filter].includes(x.kind));

  return (
    <Page onRefresh={moneyMoved} refreshing={feed.loading && !!feed.data} maxWidth={820}>
      <TopBar />
      <PageTitle title="Activity" sub="Support you received, gave and paid back — and why each one happened." />
      <View style={s.chips}>
        {FILTERS.map(([key, label]) => (
          <PressableScale key={key} onPress={() => setFilter(key)} accessibilityRole="button"
            accessibilityState={{ selected: filter === key }} style={[s.chip, filter === key && s.chipOn]}>
            <Text style={[s.chipText, filter === key && { color: C.onPrimary }]}>{label}</Text>
          </PressableScale>
        ))}
      </View>
      {!feed.data ? <View style={{ marginTop: 24 }}><LoadState error={feed.error} onRetry={feed.reload} /></View> : (
        <>
          <List>
            {items.length === 0 && <Text style={s.empty}>Nothing here yet.</Text>}
            {items.map((x, i) => {
              const [icon, tint] = LOOK[x.kind];
              const expanded = open === x.id;
              return (
                <PressableScale key={x.id} onPress={() => setOpen(expanded ? null : x.id)} accessibilityRole="button"
                  accessibilityState={{ expanded }} accessibilityHint="Shows why this happened">
                  <Row first={i === 0} left={<Avatar tint={tint}><Icon name={icon} size={18} color={tint} /></Avatar>}
                    title={x.title} sub={`${x.status} · ${monthDay(x.date)}`} right={<Amount>{money(x.amount, 0)}</Amount>} />
                  {expanded && (
                    <View style={s.why}>
                      <Text style={s.whyText}>{x.why}</Text>
                      {x.reference ? <Text style={s.ref}>Bank reference {x.reference.slice(0, 8)}…</Text> : null}
                    </View>
                  )}
                </PressableScale>
              );
            })}
          </List>
          <Fine>Only your own side is ever shown here — never anyone else’s balance, spending or reasons.</Fine>
        </>
      )}
    </Page>
  );
}

const s = StyleSheet.create({
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginBottom: 12 },
  chip: { height: 34, paddingHorizontal: 14, borderRadius: 999, borderWidth: 1, borderColor: C.line2, justifyContent: 'center' },
  chipOn: { backgroundColor: C.primary, borderColor: C.primary },
  chipText: { fontFamily: F.bodySemi, fontSize: 13, color: C.text },
  empty: { fontFamily: F.body, fontSize: 14, color: C.text2, padding: 16 },
  why: { paddingLeft: 56, paddingRight: 8, paddingBottom: 12, gap: 6 },
  whyText: { fontFamily: F.body, fontSize: 14, lineHeight: 20, color: C.text2 },
  ref: { fontFamily: F.cond, fontSize: 12, color: C.text3 },
});

/**
 * The approval card for an agent-proposed money move. The agent never moves money itself: nothing
 * happens until the user taps Approve here, which calls POST /actions/{id}/approve.
 * Outcomes follow the backend contract: 503 = nothing moved (retry is safe), 502 = outcome unknown
 * (never offer a retry), 409 = already handled.
 */
import { useState } from 'react';
import { StyleSheet, View } from 'react-native';

import { C } from '@/constants/runway';
import { httpStatus } from '@/hooks/use-load';
import { api } from '@/lib/api';
import { money } from '@/lib/format';
import { setStore, useStore } from '@/lib/store';
import type { PendingAction } from '@/lib/types';

import { Icon } from './icons';
import { Btn, Caps, Num, T } from './ui';

type Phase = 'waiting' | 'confirming' | 'done' | 'declined' | 'retry' | 'checking' | 'handled';

export function ApprovalCard({ action, compact = false, onDone, onViewRunway }: {
  action: PendingAction;
  /** Today's inline version: no big amount, buttons on the right */
  compact?: boolean;
  onDone?: () => void;
  onViewRunway?: () => void;
}) {
  const store = useStore();
  const [phase, setPhase] = useState<Phase>('waiting');
  const amount = action.amount ?? 0;

  async function approve() {
    setPhase('confirming');
    try {
      // TODO(auth): Auth0 confirmation happens here once app/src/lib/auth.ts lands.
      await api.approve(action.id);
      setStore({ approvedAmount: store.approvedAmount + amount, celebrate: true });
      setPhase('done');
      onDone?.();
    } catch (e) {
      const code = httpStatus(e instanceof Error ? e.message : '');
      setPhase(code === 502 ? 'checking' : code === 409 ? 'handled' : 'retry');
    }
  }

  const head = (icon: string, tone: string, title: string) => (
    <View style={s.hd}>
      <View style={[s.ic, { backgroundColor: `${tone}29` }]}><Icon name={icon} size={18} color={tone} /></View>
      <Caps size={15} style={{ flex: 1 }}>{title}</Caps>
    </View>
  );

  if (phase === 'done') {
    return (
      <View style={[s.card, compact && s.compact]}>
        {head('check', C.green, 'Transfer complete')}
        <T tone="dim" style={{ marginTop: 8 }}>{action.description}. Checking now stays above your floor.</T>
        {onViewRunway ? <Caps tone="blue" size={14} style={{ marginTop: 10 }} onPress={onViewRunway} accessibilityRole="link">View your runway →</Caps> : null}
      </View>
    );
  }
  if (phase === 'declined') {
    return <View style={[s.card, compact && s.compact]}>{head('close', C.text2, 'Declined')}<T tone="dim" style={{ marginTop: 8 }}>Nothing moved. Ask again anytime.</T></View>;
  }
  if (phase === 'checking') {
    return <View style={[s.card, compact && s.compact]}>{head('shield', C.amber, "We're checking with the bank")}<T tone="dim" style={{ marginTop: 8 }}>The transfer may be incomplete. Don&apos;t try again — we&apos;ll update you.</T></View>;
  }
  if (phase === 'handled') {
    return <View style={[s.card, compact && s.compact]}>{head('check', C.text2, 'Already handled')}<T tone="dim" style={{ marginTop: 8 }}>This request was already approved or declined.</T></View>;
  }

  return (
    <View style={[s.card, compact && s.compact]}>
      {head('shield', C.blue, 'Approval needed')}
      <T tone="dim" style={{ marginTop: 12 }}>{action.description}</T>
      {!compact && <Num size={40} style={{ marginTop: 4 }}>{money(amount, 0)}</Num>}
      <T tone="dim" style={{ fontSize: 13, marginTop: 6 }}>
        {phase === 'retry' ? "The bank didn't accept it. Nothing moved — try again." : 'You confirm with Auth0. Nothing moves until you approve.'}
      </T>
      <View style={s.btns}>
        <Btn label="Decline" ghost style={{ flex: 1 }} disabled={phase === 'confirming'} onPress={() => setPhase('declined')} />
        <Btn label={phase === 'confirming' ? 'Confirming…' : phase === 'retry' ? 'Try again' : `Approve ${money(amount, 0)}`} style={{ flex: 1 }}
          disabled={phase === 'confirming'} onPress={approve} />
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  card: { padding: 16, borderRadius: 14, backgroundColor: C.card, borderWidth: 1, borderColor: C.line, alignSelf: 'stretch' },
  compact: { backgroundColor: C.card2, borderWidth: 0, padding: 12, borderRadius: 10 },
  hd: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  ic: { width: 32, height: 32, borderRadius: 7, alignItems: 'center', justifyContent: 'center' },
  btns: { flexDirection: 'row', gap: 8, marginTop: 14 },
});

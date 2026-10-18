/**
 * The approval card for anything Ask Runway set up: a money move, a request, paying a supporter back, or a
 * circle change. The agent never acts itself: nothing happens until the user taps Approve here, which
 * calls POST /actions/{id}/approve.
 * Outcomes follow the backend contract: 503 = nothing moved (retry is safe), 502 = outcome unknown
 * (never offer a retry), 409 = already handled, 422 = refused, with the server's reason.
 */
import { useState } from 'react';
import { StyleSheet, View } from 'react-native';

import { C } from '@/constants/runway';
import { httpStatus } from '@/hooks/use-load';
import { api } from '@/lib/api';
import { money } from '@/lib/format';
import { setStore, useStore, moneyMoved } from '@/lib/store';
import type { PendingAction } from '@/lib/types';

import { Icon } from './icons';
import { Btn, Caps, Num, T } from './ui';

type Phase = 'waiting' | 'confirming' | 'done' | 'declined' | 'retry' | 'checking' | 'handled' | 'refused';

const DONE_TITLE: Record<PendingAction['kind'], string> = {
  transfer: 'Transfer complete',
  reschedule_bill: 'Done',
  p2p_request: 'Request sent',
  person_request: 'Request sent',
  person_send: 'Sent',
  repay: 'Paid back',
  pause_support: 'Support paused',
  resume_support: 'Support back on',
  circle_create: 'Circle created',
  circle_invite: 'Invite sent',
  circle_remove: 'Removed',
  circle_leave: 'You left the circle',
  circle_accept: 'You joined',
  circle_decline: 'Invitation declined',
  circle_link: 'Your invite link',
};

export function ApprovalCard({ action, compact = false, onDone, onViewRunway }: {
  action: PendingAction;
  /** Today's inline version: no big amount, buttons on the right */
  compact?: boolean;
  onDone?: () => void;
  onViewRunway?: () => void;
}) {
  const store = useStore();
  const [phase, setPhase] = useState<Phase>('waiting');
  const [result, setResult] = useState<PendingAction | null>(null); // a circle link comes back in the description
  const [why, setWhy] = useState<string | null>(null);
  const amount = action.amount ?? 0;
  const hasAmount = action.amount != null && action.amount > 0; // a pause or a circle change moves no money
  // a request only asks; nothing reaches checking until the contact pays, so the balance mustn't jump
  const isRequest = action.kind === 'p2p_request' || action.kind === 'person_request';
  const movesMoney = action.kind === 'transfer' || action.kind === 'person_send' || action.kind === 'repay';
  const dp = isRequest || amount % 1 ? 2 : 0; // a split share like $33.33 must show its cents; transfers are whole steps

  async function approve() {
    setPhase('confirming');
    try {
      // TODO(auth): Auth0 confirmation happens here once app/src/lib/auth.ts lands.
      setResult(await api.approve(action.id));
      moneyMoved(); // every screen re-fetches the new balances
      // only savings → checking lifts the balance the chart shows before the re-fetch lands
      if (action.kind === 'transfer') setStore({ approvedAmount: store.approvedAmount + amount, celebrate: true });
      setPhase('done');
      onDone?.();
    } catch (e) {
      const m = e instanceof Error ? e.message : '';
      const code = httpStatus(m);
      if (code === 422) {
        setWhy(m.match(/"detail":"([^"]+)"/)?.[1] ?? null);
        setPhase('refused');
        return;
      }
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
    const said = (result ?? action).description;
    const text = action.kind === 'transfer' ? `${said}. You're back above your cushion.`
      : isRequest ? `${said}. You'll see it under who owes you until it's paid.`
      : `${said}.`;
    return (
      <View style={[s.card, compact && s.compact]}>
        {head('check', C.green, DONE_TITLE[action.kind])}
        <T tone="dim" style={{ marginTop: 8 }} selectable={action.kind === 'circle_link'}>{text}</T>
        {onViewRunway && movesMoney ? <Caps tone="blue" size={14} style={{ marginTop: 10 }} onPress={onViewRunway} accessibilityRole="link">View your runway →</Caps> : null}
      </View>
    );
  }
  if (phase === 'declined') {
    return <View style={[s.card, compact && s.compact]}>{head('close', C.text2, 'Declined')}<T tone="dim" style={{ marginTop: 8 }}>Nothing happened. Ask again anytime.</T></View>;
  }
  if (phase === 'checking') {
    return <View style={[s.card, compact && s.compact]}>{head('shield', C.amber, "We're checking with the bank")}<T tone="dim" style={{ marginTop: 8 }}>The {isRequest ? 'request' : 'transfer'} may be incomplete. Don&apos;t try again — we&apos;ll update you.</T></View>;
  }
  if (phase === 'handled') {
    return <View style={[s.card, compact && s.compact]}>{head('check', C.text2, 'Already handled')}<T tone="dim" style={{ marginTop: 8 }}>This request was already approved or declined.</T></View>;
  }
  if (phase === 'refused') {
    return <View style={[s.card, compact && s.compact]}>{head('shield', C.amber, "Runway didn't do this")}<T tone="dim" style={{ marginTop: 8 }}>{why ?? "It couldn't go through right now."} Nothing happened.</T></View>;
  }

  const footer = phase === 'retry' ? "The bank didn't accept it. Nothing moved — try again."
    : action.kind === 'transfer' ? 'You confirm with Auth0. Nothing moves until you approve.'
    : isRequest ? 'Nothing is sent until you approve.'
    : movesMoney ? 'Nothing moves until you approve.'
    : 'Nothing changes until you approve.';
  const label = phase === 'confirming' ? 'Confirming…' : phase === 'retry' ? 'Try again'
    : isRequest ? `Send request ${money(amount, dp)}`
    : hasAmount ? `Approve ${money(amount, dp)}` : 'Approve';

  return (
    <View style={[s.card, compact && s.compact]}>
      {head('shield', C.blue, 'Approval needed')}
      <T tone="dim" style={{ marginTop: 12 }}>{action.description}</T>
      {!compact && hasAmount && <Num size={40} style={{ marginTop: 4 }}>{money(amount, dp)}</Num>}
      <T tone="dim" style={{ fontSize: 13, marginTop: 6 }}>{footer}</T>
      <View style={s.btns}>
        <Btn label="Decline" ghost style={{ flex: 1 }} disabled={phase === 'confirming'} onPress={() => setPhase('declined')} />
        <Btn label={label} style={{ flex: 1 }} disabled={phase === 'confirming'} onPress={approve} />
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

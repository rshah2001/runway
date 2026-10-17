// Family — owner: an2thu. The family safety net (docs/SAFETY_NET.md) one tab away from Today:
// who covers you until payday, the limits you set for others (−/+), requests waiting for your answer,
// who owes you, and what happened lately. Every number comes from GET /safety-net and GET /p2p;
// this screen only picks the words. Only the lender can change their own limit; a request sent to the
// lender's phone (Auth0 push) can only be approved there.
import { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { Icon } from '@/components/rw/icons';
import { Amount, Avatar, Fine, List, Row, SectionLabel } from '@/components/rw/list';
import { PageTitle, TopBar } from '@/components/rw/top-bar';
import { LoadState, Page, PressableScale } from '@/components/rw/ui';
import { C, F } from '@/constants/runway';
import { useLoad } from '@/hooks/use-load';
import { api } from '@/lib/api';
import { money, monthDay, plain, weekdayDate } from '@/lib/format';
import type { Bridge, SafetyEvent, SafetyLimit } from '@/lib/types';

/** The backend accepts $0–$1,000; steps of $50 keep the stepper to a few taps. */
const LIMIT_STEP = 50;
const LIMIT_MAX = 1000;
/** Bridges still in flight: money that is with someone right now, or about to be. */
const OPEN: Bridge['status'][] = ['funding', 'active', 'repaying', 'repay_failed'];


export default function FamilyScreen() {
  const sn = useLoad(() => api.safetyNet());
  const p2p = useLoad(() => api.p2p());
  const reload = () => { sn.reload(); p2p.reload(); };

  const d = sn.data;
  const lender = !!d?.limits_i_set.length;
  return (
    <Page onRefresh={reload} refreshing={sn.loading && !!d}>
      <TopBar />
      <PageTitle title="Family" sub={lender
        ? 'How much Runway may move from you, without asking, to cover someone until their payday.'
        : 'People who agreed to cover you until payday. Nobody has to ask.'} />
      {!d ? <View style={{ marginTop: 24 }}><LoadState error={sn.error} onRetry={reload} /></View> : (
        <>
          {d.approvals_waiting.length > 0 && (
            <>
              <SectionLabel>Needs your answer</SectionLabel>
              {d.approvals_waiting.map((b) => <AskCard key={b.id} b={b} onDone={reload} />)}
            </>
          )}

          {d.limits_for_me.length > 0 && (
            <>
              <SectionLabel>Covering you</SectionLabel>
              <List>
                {d.limits_for_me.map((l, i) => {
                  const out = d.borrowed.find((b) => b.lender === l.lender && OPEN.includes(b.status));
                  const asked = d.borrowed.find((b) => b.lender === l.lender && b.status === 'pending_approval');
                  return (
                    <Row key={l.lender} first={i === 0} left={<Avatar name={l.lender_name} />} title={l.lender_name}
                      sub={!l.enabled ? 'Paused'
                        : asked ? `Asked for ${money(asked.amount, 0)} · waiting for ${l.lender_name}`
                        : out ? `${money(out.amount, 0)} with you now · goes back ${weekdayDate(out.due_date)}`
                        : `Up to ${money(l.limit, 0)}`}
                      right={<Amount>{money(l.remaining, 0)} left</Amount>} />
                  );
                })}
              </List>
              <Fine>They set these limits. Money always goes back on your next payday.</Fine>
            </>
          )}

          {lender && (
            <>
              <SectionLabel>Your limits</SectionLabel>
              <List>
                {d.limits_i_set.map((l, i) => (
                  <LimitRow key={l.borrower} first={i === 0} l={l} out={d.lent.find((b) => b.borrower === l.borrower && OPEN.includes(b.status))} onSaved={sn.reload} />
                ))}
              </List>
              <Fine>Only you can change these. Over the limit, Runway asks you on your phone first.</Fine>
            </>
          )}

          <OwesYou p2p={p2p.data} onAsked={p2p.reload} />

          {d.events.length > 0 && (
            <>
              <SectionLabel>Recent</SectionLabel>
              <List>
                {d.events.slice(0, 5).map((e, i) => <EventRow key={`${e.at}-${i}`} e={e} first={i === 0} />)}
              </List>
            </>
          )}
        </>
      )}
    </Page>
  );
}

/** A lender's own limit for one person, with −/+. Shows the new value at once; puts it back if the server says no. */
function LimitRow({ l, out, first, onSaved }: { l: SafetyLimit; out?: Bridge; first: boolean; onSaved: () => void }) {
  const [value, setValue] = useState(l.limit);
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState(false);

  async function save(next: number) {
    const prev = value;
    setValue(next);
    setSaving(true);
    setFailed(false);
    try {
      await api.setSafetyLimit(l.lender, l.borrower, next, next > 0);
      onSaved();
    } catch {
      setValue(prev);
      setFailed(true);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Row first={first} left={<Avatar name={l.borrower_name} />} title={l.borrower_name}
      sub={failed ? 'Couldn’t save. Try again.' : value === 0 ? 'Off' : out ? `${money(out.amount, 0)} with them now · back ${weekdayDate(out.due_date)}` : 'Nothing out'}
      right={
        <View style={s.stepper}>
          <Step label="−" disabled={saving || value <= 0} onPress={() => save(Math.max(0, value - LIMIT_STEP))} a11y={`Lower ${l.borrower_name}'s limit`} />
          <Text style={s.stepValue}>{money(value, 0)}</Text>
          <Step label="+" disabled={saving || value >= LIMIT_MAX} onPress={() => save(Math.min(LIMIT_MAX, value + LIMIT_STEP))} a11y={`Raise ${l.borrower_name}'s limit`} />
        </View>
      } />
  );
}

function Step({ label, disabled, onPress, a11y }: { label: string; disabled: boolean; onPress: () => void; a11y: string }) {
  return (
    <PressableScale onPress={onPress} disabled={disabled} accessibilityRole="button" accessibilityLabel={a11y} style={[s.step, disabled && { opacity: 0.4 }]}>
      <Text style={s.stepText}>{label}</Text>
    </PressableScale>
  );
}

/** Someone asked for more than your limit: approve or decline here (or on your phone, for an Auth0 push). */
function AskCard({ b, onDone }: { b: Bridge; onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const onPhone = b.approval_channel === 'auth0_push';

  async function answer(approve: boolean) {
    setBusy(true);
    setFailed(false);
    try {
      await (approve ? api.approveBridge(b.id) : api.declineBridge(b.id));
      onDone();
    } catch {
      setFailed(true);
      setBusy(false);
    }
  }

  return (
    <View style={s.ask}>
      <Text style={s.askTitle}>{b.borrower_name} needs {money(b.amount, 0)}</Text>
      <Text style={s.askBody}>{b.reason} It comes back {weekdayDate(b.due_date)}.</Text>
      {failed && <Text style={[s.askBody, { color: C.red }]}>That didn’t go through. Nothing moved.</Text>}
      <View style={s.askBtns}>
        <PressableScale onPress={() => answer(false)} disabled={busy} accessibilityRole="button" style={[s.btn, s.no]}>
          <Text style={[s.btnText, { color: C.text2 }]}>Decline</Text>
        </PressableScale>
        {onPhone
          ? <View style={[s.btn, s.no]}><Text style={[s.btnText, { color: C.text2, fontSize: 14 }]}>Approve on your phone</Text></View>
          : (
            <PressableScale onPress={() => answer(true)} disabled={busy} accessibilityRole="button" style={[s.btn, s.yes, busy && { opacity: 0.7 }]}>
              <Text style={[s.btnText, { color: '#111' }]}>{busy ? 'Sending…' : `Approve ${money(b.amount, 0)}`}</Text>
            </PressableScale>
          )}
      </View>
    </View>
  );
}

/** Friends who owe you (GET /p2p), with a one-tap request to pay you back. */
function OwesYou({ p2p, onAsked }: { p2p: Awaited<ReturnType<typeof api.p2p>> | null; onAsked: () => void }) {
  const [sending, setSending] = useState<string | null>(null);
  const owed = (p2p?.contacts ?? []).filter((c) => c.owes_you > 0);
  if (!owed.length) return null;

  async function ask(id: string, amount: number) {
    setSending(id);
    try {
      await api.p2pRequest(id, amount, 'Paying me back');
      onAsked();
    } finally {
      setSending(null);
    }
  }

  return (
    <>
      <SectionLabel>Owes you</SectionLabel>
      <List>
        {owed.map((c, i) => {
          const open = p2p?.requests.find((r) => r.contact_id === c.id && (r.status === 'open' || r.status === 'settling'));
          return (
            <Row key={c.id} first={i === 0} left={<Avatar name={c.name} />} title={c.name}
              sub={open ? `${plain(open.memo)} · asked ${monthDay(open.created)}` : c.relation}
              right={
                <View style={s.owe}>
                  <Amount tone="green">{money(c.owes_you, 0)}</Amount>
                  {!open && (
                    <PressableScale onPress={() => ask(c.id, c.owes_you)} disabled={sending === c.id} accessibilityRole="button"
                      accessibilityLabel={`Ask ${c.name} for ${money(c.owes_you, 0)}`} style={s.askBtn}>
                      <Text style={s.askBtnText}>{sending === c.id ? '…' : 'Ask'}</Text>
                    </PressableScale>
                  )}
                </View>
              } />
          );
        })}
      </List>
    </>
  );
}

const EVENT_ICON: Record<string, [string, string]> = {
  bridge_auto: ['shield', C.green],
  repaid: ['check', C.green],
  approval_needed: ['shield', C.amber],
};

function EventRow({ e, first }: { e: SafetyEvent; first: boolean }) {
  const [icon, tint] = EVENT_ICON[e.kind] ?? ['transfer', C.text2];
  const day = e.at.slice(0, 10);
  const today = new Date().toISOString().slice(0, 10);
  return (
    <Row first={first} left={<Avatar tint={tint}><Icon name={icon} size={18} color={tint} /></Avatar>}
      title={plain(e.message)} sub={day === today ? 'Today' : monthDay(day)} />
  );
}

const s = StyleSheet.create({
  stepper: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  step: { width: 34, height: 34, borderRadius: 17, backgroundColor: C.card2, alignItems: 'center', justifyContent: 'center' },
  stepText: { fontFamily: F.bodySemi, fontSize: 19, color: C.text, lineHeight: 22 },
  stepValue: { fontFamily: F.condBold, fontSize: 19, color: C.text, minWidth: 56, textAlign: 'center', fontVariant: ['tabular-nums'] },
  ask: { borderRadius: 20, backgroundColor: C.card, padding: 16, borderWidth: 1, borderColor: `${C.amber}55` },
  askTitle: { fontFamily: F.bodySemi, fontSize: 17, color: C.text },
  askBody: { fontFamily: F.body, fontSize: 14, lineHeight: 20, color: C.text2, marginTop: 4 },
  askBtns: { flexDirection: 'row', gap: 10, marginTop: 14 },
  btn: { flex: 1, height: 46, borderRadius: 999, alignItems: 'center', justifyContent: 'center' },
  no: { borderWidth: 1, borderColor: '#2f363c' },
  yes: { backgroundColor: '#fff' },
  btnText: { fontFamily: F.bodySemi, fontSize: 15 },
  owe: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  askBtn: { height: 32, paddingHorizontal: 14, borderRadius: 999, backgroundColor: '#fff', justifyContent: 'center' },
  askBtnText: { fontFamily: F.bodySemi, fontSize: 13, color: '#111' },
});

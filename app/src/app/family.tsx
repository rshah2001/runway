// Family — owner: an2thu. The family safety net (docs/SAFETY_NET.md) one tab away from Today:
// who covers you until payday, the limits you set for others (−/+), requests waiting for your answer,
// who owes you, and what happened lately. Every number comes from GET /safety-net and GET /p2p;
// this screen only picks the words. Only the lender can change their own limit; a request sent to the
// lender's phone (Auth0 push) can only be approved there.
// Also here: asking the family for help before a dip, paying a bridge back early, settling and sending
// money between friends, and — for the three demo accounts — resetting the demo.
import { Fragment, type ReactNode, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { Icon } from '@/components/rw/icons';
import { Amount, Avatar, Fine, List, Row, SectionLabel } from '@/components/rw/list';
import { PageTitle, TopBar } from '@/components/rw/top-bar';
import { LoadState, Page, PressableScale } from '@/components/rw/ui';
import { C, F } from '@/constants/runway';
import { useLoad } from '@/hooks/use-load';
import { api } from '@/lib/api';
import { useSession } from '@/lib/session';
import { moneyMoved, useStore } from '@/lib/store';
import { money, monthDay, plain, weekdayDate } from '@/lib/format';
import type { Bridge, P2PPayment, P2PSummary, SafetyEvent, SafetyLimit, SafetyNetSummary } from '@/lib/types';

/** The backend accepts $0–$1,000; steps of $50 keep the stepper to a few taps. */
const LIMIT_STEP = 50;
const LIMIT_MAX = 1000;
/** Bridges still in flight: money that is with someone right now, or about to be. */
const OPEN: Bridge['status'][] = ['funding', 'active', 'repaying', 'repay_failed'];


export default function FamilyScreen() {
  // keyed on the app-wide money signal: a payment here, an approval in the chat or a reset all refresh it
  const version = String(useStore().dataVersion);
  const sn = useLoad(() => api.safetyNet(), version);
  const p2p = useLoad(() => api.p2p(), version);
  const fc = useLoad(() => api.forecast(30), version);
  const me = useLoad(() => api.me(), version);
  const reload = moneyMoved; // after any action here, every screen (Today, Spending, this one) re-fetches

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
          {me.data?.family_cover !== false && <HelpCard d={d} floor={fc.data?.safe_floor} onDone={reload} />}

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
                      right={out && (out.status === 'active' || out.status === 'repay_failed')
                        ? <PayBack b={out} onDone={reload} />
                        : <Amount>{money(l.remaining, 0)} left</Amount>} />
                  );
                })}
              </List>
              <Fine>They set these limits. Money always goes back on your next payday.</Fine>
              <WhatTheySee on={me.data?.family_cover} onChanged={reload} />
            </>
          )}

          {lender && (
            <>
              <SectionLabel>Your limits</SectionLabel>
              <List>
                {d.limits_i_set.map((l, i) => (
                  <LimitRow key={l.borrower} first={i === 0} l={l} out={d.lent.find((b) => b.borrower === l.borrower && OPEN.includes(b.status))} onSaved={reload} />
                ))}
              </List>
              <Fine>Only you can change these. Over the limit, Runway asks you on your phone first.</Fine>
            </>
          )}

          <OwesYou p2p={p2p.data} onAsked={reload} />
          <SendMoney p2p={p2p.data} onSent={reload} />

          <Recent events={d.events} payments={p2p.data?.payments ?? []} />
        </>
      )}
      <DemoReset onDone={reload} />
    </Page>
  );
}

/** The server's own words for a refused money action (a 409 says why), or a plain fallback. */
function reason(e: unknown, fallback = 'That didn’t go through. Please try again.'): string {
  const m = e instanceof Error ? e.message : '';
  return m.match(/"detail":"([^"]+)"/)?.[1] ?? fallback;
}

/** A pill button that asks once ("Pay $100?") before it acts. Feedback on press-down via PressableScale. */
function TwoTap({ label, confirm, onPress, light = true }: { label: string; confirm: string; onPress: () => Promise<void>; light?: boolean }) {
  const [armed, setArmed] = useState(false);
  const [busy, setBusy] = useState(false);
  async function tap() {
    if (!armed) return setArmed(true);
    setBusy(true);
    try {
      await onPress();
    } finally {
      setBusy(false);
      setArmed(false);
    }
  }
  return (
    <View style={s.owe}>
      {armed && !busy && (
        <PressableScale onPress={() => setArmed(false)} accessibilityRole="button" style={[s.askBtn, s.ghostBtn]}>
          <Text style={[s.askBtnText, { color: C.text2 }]}>Cancel</Text>
        </PressableScale>
      )}
      <PressableScale onPress={tap} disabled={busy} accessibilityRole="button" style={[s.askBtn, !light && s.ghostBtn, busy && { opacity: 0.7 }]}>
        <Text style={[s.askBtnText, !light && { color: C.text }]}>{busy ? '…' : armed ? confirm : label}</Text>
      </PressableScale>
    </View>
  );
}

/**
 * Before a dip, with nobody covering it yet: one tap asks the family. Under a lender's limit it's
 * covered at once; over it, the lender is asked (on their phone, with Auth0 push) and it shows here.
 */
function HelpCard({ d, floor, onDone }: { d: SafetyNetSummary; floor?: number; onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const low = d.projected_low;
  const inFlight = d.borrowed.some((b) => OPEN.includes(b.status) || b.status === 'pending_approval');
  const canHelp = d.limits_for_me.some((l) => l.enabled && l.remaining > 0);
  if (!low || floor === undefined || low.balance >= floor || inFlight || !canHelp) return null;
  async function ask() {
    setBusy(true);
    setNote(null);
    try {
      const [decision] = await api.runSafetyNet();
      onDone();
      if (decision && !decision.executed) setNote(decision.reason);
    } catch (e) {
      setNote(reason(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <View style={[s.ask, { borderColor: `${C.red}55`, marginTop: 8 }]}>
      <Text style={s.askTitle}>You dip to {money(low.balance, 0)} on {weekdayDate(low.date)}</Text>
      <Text style={s.askBody}>That’s before payday, under the {money(floor, 0)} you keep. Your family agreed to cover gaps like this. Runway does the asking, and they only see the amount and the day it goes back.</Text>
      {note && <Text style={[s.askBody, { color: C.amber }]}>{plain(note)}</Text>}
      <View style={s.askBtns}>
        <PressableScale onPress={ask} disabled={busy} accessibilityRole="button" style={[s.btn, s.yes, busy && { opacity: 0.7 }]}>
          <Text style={[s.btnText, { color: '#111' }]}>{busy ? 'Covering…' : 'Cover it with family'}</Text>
        </PressableScale>
      </View>
    </View>
  );
}

/**
 * What the people covering you can see, and the switch to turn family cover off. People told us the
 * embarrassment of family seeing their money is why they'd never use a safety net, so the helper's
 * view is fixed on the server (safety_views.for_lender): who, how much, when it comes back — never
 * your balance, your spending, or what it was for. Off: no relative's money moves to you, even with a
 * limit set, and nobody is asked.
 */
function WhatTheySee({ on, onChanged }: { on: boolean | undefined; onChanged: () => void }) {
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState(false);
  async function toggle() {
    if (on === undefined) return;
    setSaving(true);
    setFailed(false);
    try {
      await api.setPreferences({ family_cover: !on });
      onChanged();
    } catch {
      setFailed(true);
    } finally {
      setSaving(false);
    }
  }
  return (
    <View style={s.privacy}>
      <View style={s.privacyHead}>
        <Icon name="shield" size={18} color={C.green} />
        <Text style={s.askTitle}>What they can see</Text>
      </View>
      <View style={s.seeRow}><Icon name="check" size={16} color={C.green} /><Text style={s.seeText}>How much they covered, and the day it goes back</Text></View>
      <View style={s.seeRow}><Icon name="close" size={16} color={C.text3} /><Text style={s.seeText}>Never your balance, your spending, or what it was for</Text></View>
      <View style={s.seeRow}><Icon name="check" size={16} color={C.green} /><Text style={s.seeText}>You never have to ask: Runway does it for you</Text></View>
      {on !== undefined && (
        <PressableScale onPress={toggle} disabled={saving} accessibilityRole="switch" accessibilityState={{ checked: on }}
          accessibilityLabel="Let family cover me" style={s.switchRow}>
          <View style={{ flex: 1 }}>
            <Text style={s.switchTitle}>Let family cover me</Text>
            <Text style={s.seeText}>{on ? 'On. Turn it off any time.' : 'Off. Nobody’s money moves to you, and nobody is asked.'}</Text>
          </View>
          <View style={[s.track, on && s.trackOn, saving && { opacity: 0.6 }]}><View style={[s.knob, on && s.knobOn]} /></View>
        </PressableScale>
      )}
      {failed && <Text style={[s.seeText, { color: C.red, marginTop: 6 }]}>Couldn’t save that. Please try again.</Text>}
    </View>
  );
}

/** Pay a bridge back before payday — refused (with the reason) if it would take you under what you keep. */
function PayBack({ b, onDone }: { b: Bridge; onDone: () => void }) {
  const [note, setNote] = useState<string | null>(null);
  return (
    <View style={{ alignItems: 'flex-end', gap: 4, maxWidth: 220 }}>
      <TwoTap label="Pay back" confirm={`Pay ${money(b.amount, 0)}?`} onPress={async () => {
        setNote(null);
        try {
          await api.repayBridge(b.id);
          onDone();
        } catch (e) {
          setNote(reason(e));
        }
      }} />
      {note && <Text style={[s.fineText, { textAlign: 'right' }]}>{plain(note)}</Text>}
    </View>
  );
}

const SEND_AMOUNTS = [10, 20, 50];

/** Send a friend money: pick who, pick how much, confirm. A real Nessie move (transfer + deposit). */
function SendMoney({ p2p, onSent }: { p2p: P2PSummary | null; onSent: () => void }) {
  const [to, setTo] = useState<string | null>(null);
  const [amount, setAmount] = useState<number | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const contacts = p2p?.contacts ?? [];
  if (!contacts.length) return null;
  const who = contacts.find((c) => c.id === to);
  return (
    <>
      <SectionLabel>Send money</SectionLabel>
      <View style={[s.ask, { borderColor: '#2f363c' }]}>
        <View style={s.chips}>
          {contacts.map((c) => (
            <Pick key={c.id} on={to === c.id} label={c.name} onPress={() => { setTo(c.id); setNote(null); }} />
          ))}
        </View>
        <View style={[s.chips, { marginTop: 10 }]}>
          {SEND_AMOUNTS.map((n) => (
            <Pick key={n} on={amount === n} label={money(n, 0)} onPress={() => { setAmount(n); setNote(null); }} />
          ))}
        </View>
        {note && <Text style={s.askBody}>{note}</Text>}
        {who && amount ? (
          <View style={[s.askBtns, { justifyContent: 'flex-start' }]}>
            <TwoTap label={`Send ${who.name} ${money(amount, 0)}`} confirm="Tap again to send" onPress={async () => {
              try {
                await api.p2pSend(who.id, amount, 'Sent with Runway');
                setNote(`Sent ${money(amount, 0)} to ${who.name}.`);
                setAmount(null);
                onSent();
              } catch (e) {
                setNote(reason(e));
              }
            }} />
          </View>
        ) : (
          <Text style={s.fineText}>Pick a person and an amount.</Text>
        )}
      </View>
    </>
  );
}

function Pick({ on, label, onPress }: { on: boolean; label: string; onPress: () => void }) {
  return (
    <PressableScale onPress={onPress} accessibilityRole="button" accessibilityState={{ selected: on }} style={[s.pick, on && s.pickOn]}>
      <Text style={[s.askBtnText, { color: on ? '#111' : C.text }]}>{label}</Text>
    </PressableScale>
  );
}

const DEMO = ['maya', 'jordan', 'sam'];

/** Demo accounts only: rebuild Maya, Jordan and Sam, and pause automatic help until it's shown live. */
function DemoReset({ onDone }: { onDone: () => void }) {
  const session = useSession();
  const [state, setState] = useState<string | null>(null);
  if (session.mode !== 'signed-in' || !DEMO.includes(session.persona)) return null;
  async function reset() {
    setState('Rebuilding Maya, Jordan and Sam… about a minute.');
    try {
      await api.demoReset();
      for (let i = 0; i < 90; i++) {
        await new Promise((r) => setTimeout(r, 3000));
        const st = await api.demoStatus();
        if (st.state === 'done') {
          setState('The demo is fresh. Automatic help waits until someone taps “Ask family to cover it”.');
          onDone();
          return;
        }
        if (st.state === 'failed') {
          setState(`The reset didn’t finish (${st.error ?? 'error'}). Try again.`);
          return;
        }
      }
      setState('Still rebuilding. Refresh in a minute.');
    } catch (e) {
      setState(reason(e, 'Couldn’t start the reset.'));
    }
  }
  return (
    <View style={{ alignItems: 'center', marginTop: 28, gap: 8 }}>
      <TwoTap label="Reset demo" confirm="Reset all three demo accounts?" light={false} onPress={reset} />
      {state && <Text style={[s.fineText, { textAlign: 'center' }]}>{state}</Text>}
    </View>
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
                  {!open ? (
                    <PressableScale onPress={() => ask(c.id, c.owes_you)} disabled={sending === c.id} accessibilityRole="button"
                      accessibilityLabel={`Ask ${c.name} for ${money(c.owes_you, 0)}`} style={s.askBtn}>
                      <Text style={s.askBtnText}>{sending === c.id ? '…' : 'Ask'}</Text>
                    </PressableScale>
                  ) : open.status === 'open' ? (
                    // the friend pays it: a real Nessie move from their account to yours
                    <TwoTap label="Mark paid" confirm="They paid?" onPress={async () => {
                      await api.p2pSettle(open.id);
                      onAsked();
                    }} />
                  ) : null}
                </View>
              } />
          );
        })}
      </List>
    </>
  );
}

/**
 * Everything that happened, newest first: what the safety net did and money sent to or received from
 * friends — so a payment shows up here the moment it's made.
 */
function Recent({ events, payments }: { events: SafetyEvent[]; payments: P2PPayment[] }) {
  type Item = { key: string; when: string; node: (first: boolean) => ReactNode };
  const items: Item[] = [
    ...events.map((e, i) => ({ key: `e-${e.at}-${i}`, when: e.at, node: (first: boolean) => <EventRow e={e} first={first} /> })),
    ...payments.map((p) => ({ key: `p-${p.id}`, when: `${p.date}T12:00:00`, node: (first: boolean) => <PaymentRow p={p} first={first} /> })),
  ].sort((a, b) => (a.when < b.when ? 1 : a.when > b.when ? -1 : 0)).slice(0, 8);
  if (!items.length) return null;
  return (
    <>
      <SectionLabel>Recent</SectionLabel>
      <List>{items.map((it, i) => <Fragment key={it.key}>{it.node(i === 0)}</Fragment>)}</List>
    </>
  );
}

function PaymentRow({ p, first }: { p: P2PPayment; first: boolean }) {
  const inbound = p.direction === 'in';
  const today = new Date().toISOString().slice(0, 10);
  return (
    <Row first={first} left={<Avatar name={p.contact} />}
      title={inbound ? `${p.contact} paid you` : `You paid ${p.contact}`}
      sub={`${plain(p.memo)} · ${p.date === today ? 'Today' : monthDay(p.date)}`}
      right={<Amount tone={inbound ? 'green' : undefined}>{`${inbound ? '+' : '−'}${money(p.amount, 0)}`}</Amount>} />
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
  privacy: { marginTop: 14, borderRadius: 20, backgroundColor: C.card, padding: 16, gap: 8 },
  privacyHead: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 2 },
  seeRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  seeText: { flex: 1, fontFamily: F.body, fontSize: 14, lineHeight: 20, color: C.text2 },
  switchRow: { flexDirection: 'row', alignItems: 'center', gap: 12, marginTop: 6, paddingTop: 12, borderTopWidth: 1, borderTopColor: C.line },
  switchTitle: { fontFamily: F.bodySemi, fontSize: 15, color: C.text },
  track: { width: 44, height: 26, borderRadius: 13, backgroundColor: C.line, padding: 3 },
  trackOn: { backgroundColor: C.green },
  knob: { width: 20, height: 20, borderRadius: 10, backgroundColor: '#fff' },
  knobOn: { transform: [{ translateX: 18 }] },
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
  ghostBtn: { backgroundColor: 'transparent', borderWidth: 1, borderColor: '#2f363c' },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  pick: { height: 36, paddingHorizontal: 16, borderRadius: 999, borderWidth: 1, borderColor: '#2f363c', justifyContent: 'center' },
  pickOn: { backgroundColor: '#fff', borderColor: '#fff' },
  fineText: { fontFamily: F.body, fontSize: 13, lineHeight: 18, color: C.text2, marginTop: 8 },
});

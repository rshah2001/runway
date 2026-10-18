// Circles — the safety net between people who trust each other (docs/SAFETY_NET.md): who has agreed to
// help you, who you've agreed to help, requests waiting for your answer, and every transfer and
// repayment. Support needs BOTH people's yes (a Quiet Support Agreement): each side agrees here for
// itself, and either can stop at any time. Every number comes from GET /safety-net, /support and
// /p2p — nobody's balance, income or spending is ever in those responses; this screen only picks words.
// Also here: asking your circle before a dip, paying support back early, sending money, the demo reset.
import { Fragment, type ReactNode, useState } from 'react';
import { Platform, Share, StyleSheet, Text, TextInput, View } from 'react-native';

import { CircleLegend, CircleMap, type CirclePerson } from '@/components/rw/circle-map';
import { Icon } from '@/components/rw/icons';
import { Amount, Avatar, Fine, List, Row, SectionLabel } from '@/components/rw/list';
import { PageTitle, TopBar } from '@/components/rw/top-bar';
import { Sheet } from '@/components/rw/sheet';
import { LoadState, Page, PressableScale, useWide } from '@/components/rw/ui';
import { alpha, C, F } from '@/constants/runway';
import { useLoad } from '@/hooks/use-load';
import { api } from '@/lib/api';
import { useSession } from '@/lib/session';
import { moneyMoved, useStore } from '@/lib/store';
import { money, monthDay, plain, weekdayDate } from '@/lib/format';
import type {
  Bridge,
  P2PPayment,
  SafetyEvent,
  SafetyLimit,
  SafetyNetSummary,
  CircleView,
  PeopleSummary,
  SupportAgreement,
  SupportSummary,
} from '@/lib/types';

/** The backend accepts $0–$1,000; steps of $50 keep the stepper to a few taps. */
const LIMIT_STEP = 50;
const LIMIT_MAX = 1000;
/** Bridges still in flight: money that is with someone right now, or about to be. */
const OPEN: Bridge['status'][] = ['funding', 'active', 'repaying', 'repay_failed', 'reconcile'];


export default function CirclesScreen() {
  // keyed on the app-wide money signal: a payment here, an approval in the chat or a reset all refresh it
  const version = String(useStore().dataVersion);
  const sn = useLoad(() => api.safetyNet(), version);
  const sup = useLoad(() => api.support(), version);
  const p2p = useLoad(() => api.p2p(), version);
  const ppl = useLoad(() => api.people(), version);
  const cir = useLoad(() => api.circles(), version);
  const fc = useLoad(() => api.forecast(30), version);
  const me = useLoad(() => api.me(), version);
  const [consent, setConsent] = useState<SupportAgreement | null>(null);
  const [picked, setPicked] = useState<string | null>(null);
  const session = useSession();
  const reload = moneyMoved; // after any action here, every screen (Today, Spending, this one) re-fetches
  const wide = useWide();

  const d = sn.data;
  return (
    <View style={{ flex: 1 }}>
    <Page onRefresh={reload} refreshing={sn.loading && !!d}>
      <TopBar />
      <PageTitle title="Circles" sub="People who’ve agreed to help you, and people you’ve agreed to help. Nobody ever sees anyone’s balance." />
      {!d ? <View style={{ marginTop: 24 }}><LoadState error={sn.error} onRetry={reload} /></View> : (
        <Columns wide={wide} left={<>
          {sup.data && (sup.data.supporters.length > 0 || sup.data.supporting.length > 0) && (
            <MyCircle me={session.name ?? 'You'} d={d} sup={sup.data} picked={picked} onPick={setPicked}
              onReview={setConsent} onDone={reload} />
          )}
          {me.data?.family_cover !== false && <HelpCard d={d} floor={fc.data?.safe_floor} onDone={reload} />}
          {wide && !!sup.data?.supporters.length && <WhatTheySee on={me.data?.family_cover} onChanged={reload} />}
        </>} right={<>
          {d.approvals_waiting.length > 0 && (
            <>
              <SectionLabel>Needs your answer</SectionLabel>
              {d.approvals_waiting.map((b) => <AskCard key={b.id} b={b} onDone={reload} />)}
            </>
          )}

          <MySupporters d={d} sup={sup.data} onAgree={setConsent} onDone={reload} />
          {!wide && !!sup.data?.supporters.length && <WhatTheySee on={me.data?.family_cover} onChanged={reload} />}
          <PeopleISupport d={d} sup={sup.data} onAgree={setConsent} onSaved={reload} />

          <OwesYou p2p={p2p.data} onAsked={reload} />
          <MyCirclesManager list={cir.data} ppl={ppl.data} onDone={reload} />
          <AskedYou ppl={ppl.data} onDone={reload} />
          <SendOrRequest ppl={ppl.data} onDone={reload} />
          <YouAsked ppl={ppl.data} />

          <Recent events={d.events} payments={[...(p2p.data?.payments ?? []), ...peoplePayments(ppl.data)]} />
        </>} />
      )}
      {d && d.borrowed.some((b) => b.status === 'active' || b.status === 'repay_failed') && <DemoPayday onDone={reload} />}
      <DemoReset onDone={reload} />
    </Page>
    {/* over the whole screen, not inside the scrolling page */}
    <ConsentSheet a={consent} onClose={() => setConsent(null)} onDone={() => { setConsent(null); reload(); }} />
    </View>
  );
}

/** Desktop: the map and its cards on the left, the lists beside them. Phones: one column. */
function Columns({ wide, left, right }: { wide: boolean; left: ReactNode; right: ReactNode }) {
  if (!wide) return <>{left}{right}</>;
  return (
    <View style={s.cols}>
      <View style={{ flex: 1.1, minWidth: 0, paddingTop: 18 }}>{left}</View>
      <View style={{ flex: 1, minWidth: 0 }}>{right}</View>
    </View>
  );
}

/** The people on my map: my supporters and the people I support, with what's out on each line. */
function circlePeople(d: SafetyNetSummary, sup: SupportSummary): CirclePerson[] {
  const status = (a: SupportAgreement): CirclePerson['status'] =>
    a.state === 'active' ? 'active' : a.state === 'revoked' || a.state === 'paused' ? 'off' : 'waiting';
  const outFrom = (slug: string) => d.borrowed.filter((b) => b.lender === slug && OPEN.includes(b.status)).reduce((t, b) => t + b.amount, 0);
  const outTo = (slug: string) => d.lent.filter((b) => b.borrower === slug && OPEN.includes(b.status)).reduce((t, b) => t + b.amount, 0);
  return [
    ...sup.supporters.map((a) => ({ key: `s-${a.supporter}`, name: a.supporter_name, role: 'supporter' as const, status: status(a), out: outFrom(a.supporter) || undefined })),
    ...sup.supporting.map((a) => ({ key: `r-${a.recipient}`, name: a.recipient_name, role: 'supported' as const, status: status(a), out: outTo(a.recipient) || undefined })),
  ];
}

/**
 * My support circle as an interactive map (components/rw/circle-map). Tapping someone shows what we've
 * agreed and what's out between us — and the action that fits (review the agreement, pay back early).
 */
function MyCircle({ me, d, sup, picked, onPick, onReview, onDone }: {
  me: string; d: SafetyNetSummary; sup: SupportSummary; picked: string | null;
  onPick: (k: string | null) => void; onReview: (a: SupportAgreement) => void; onDone: () => void;
}) {
  const people = circlePeople(d, sup);
  const borrowed = d.borrowed.some((b) => OPEN.includes(b.status));
  const protectedBy = sup.supporters.filter((a) => a.state === 'active').length;
  const helping = sup.supporting.filter((a) => a.state === 'active').length;
  const [status, tone] = borrowed ? ['Covered', C.green]
    : protectedBy ? ['Protected', C.green]
    : helping ? [`Supporting ${helping}`, C.cover]
    : ['Not set up', C.text3];
  const sel = people.find((p) => p.key === picked);
  const agreement = sel && (sel.role === 'supporter'
    ? sup.supporters.find((a) => `s-${a.supporter}` === sel.key)
    : sup.supporting.find((a) => `r-${a.recipient}` === sel.key));
  const owed = sel?.role === 'supporter' ? d.borrowed.find((b) => `s-${b.lender}` === sel.key && (b.status === 'active' || b.status === 'repay_failed')) : undefined;
  return (
    <View style={s.mapCard}>
      <View style={s.mapHead}>
        <Text style={s.askTitle}>{me === 'You' ? 'Your support circle' : `${me}’s support circle`}</Text>
        <Text style={s.fineText}>Only you see this</Text>
      </View>
      <CircleMap me={me} status={status} tone={tone} people={people} selected={picked} onSelect={onPick} />
      <CircleLegend />
      {sel && agreement ? (
        <View style={s.picked}>
          <Avatar name={sel.name} />
          <View style={{ flex: 1 }}>
            <Text style={s.switchTitle}>{sel.name} · {sel.role === 'supporter' ? 'can cover you' : 'you can cover them'}</Text>
            <Text style={s.seeText}>
              {sel.out ? `${money(sel.out, 0)} out now · ` : ''}{agreementLine(agreement)}
            </Text>
          </View>
          {owed ? <PayBack b={owed} onDone={onDone} /> : <Pill label={agreement.i_agreed ? 'Manage' : 'Review'} onPress={() => onReview(agreement)} />}
        </View>
      ) : (
        <Text style={[s.fineText, { textAlign: 'center' }]}>Each line is a separately agreed support relationship — never access to anyone’s money. Tap a person.</Text>
      )}
    </View>
  );
}

/** What an agreement looks like from my side, in a few plain words. */
function agreementLine(a: SupportAgreement): string {
  const them = a.my_side === 'recipient' ? a.supporter_name : a.recipient_name;
  switch (a.state) {
    case 'active': return a.my_side === 'recipient' ? `Ready to help · up to ${money(a.limit ?? 0, 0)}` : 'Agreed · nothing out';
    case 'paused': return a.my_side === 'recipient' ? `${them} paused this for now` : 'Paused';
    case 'revoked': return 'Stopped';
    case 'needs_both': return 'Not agreed yet';
    default:
      return a.i_agreed ? `Waiting for ${them} to agree` : a.my_side === 'recipient' ? `${them} offered to help you quietly` : `${them} asked for your support`;
  }
}

/**
 * People who may cover me. Their money only moves when we both agreed; what's out with me shows here
 * with a way to pay it back early. Their limit is the only thing of theirs I ever see.
 */
function MySupporters({ d, sup, onAgree, onDone }: {
  d: SafetyNetSummary; sup: SupportSummary | null; onAgree: (a: SupportAgreement) => void; onDone: () => void;
}) {
  const people = sup?.supporters ?? [];
  if (!people.length) return null;
  return (
    <>
      <SectionLabel>My supporters</SectionLabel>
      <List>
        {people.map((a, i) => {
          const out = d.borrowed.find((b) => b.lender === a.supporter && OPEN.includes(b.status));
          const asked = d.borrowed.find((b) => b.lender === a.supporter && b.status === 'pending_approval');
          const sub = out ? `${money(out.amount, 0)} with you now · expected back after your next verified payday`
            : asked ? `Asked for ${money(asked.amount, 0)} · waiting for ${a.supporter_name}`
            : agreementLine(a);
          return (
            <Row key={a.supporter} first={i === 0} left={<Avatar name={a.supporter_name} />} title={a.supporter_name}
              sub={sub}
              right={out && (out.status === 'active' || out.status === 'repay_failed') ? <PayBack b={out} onDone={onDone} />
                : !a.i_agreed ? <Pill label="Review" onPress={() => onAgree(a)} />
                : a.state === 'active' ? <StateDot on /> : <StateDot on={false} />} />
          );
        })}
      </List>
      <Fine>Help moves only when you’ve both agreed. It goes back automatically after your next verified payday — never sooner than it’s safe for you.</Fine>
    </>
  );
}

/** People I may cover: my limit for each (−/+), what's out with them, and requests to agree to. */
function PeopleISupport({ d, sup, onAgree, onSaved }: {
  d: SafetyNetSummary; sup: SupportSummary | null; onAgree: (a: SupportAgreement) => void; onSaved: () => void;
}) {
  const people = sup?.supporting ?? [];
  if (!people.length) return null;
  return (
    <>
      <SectionLabel>People I support</SectionLabel>
      <List>
        {people.map((a, i) => {
          const limit = d.limits_i_set.find((l) => l.borrower === a.recipient);
          const out = d.lent.find((b) => b.borrower === a.recipient && OPEN.includes(b.status));
          if (limit && (a.state === 'active' || a.state === 'paused' || a.i_agreed)) {
            return <LimitRow key={a.recipient} first={i === 0} l={limit} a={a} out={out} onSaved={onSaved} />;
          }
          return (
            <Row key={a.recipient} first={i === 0} left={<Avatar name={a.recipient_name} />} title={a.recipient_name}
              sub={agreementLine(a)} right={<Pill label="Review" onPress={() => onAgree(a)} />} />
          );
        })}
      </List>
      <Fine>Runway only ever moves up to your limit, and only when your own bills stay covered. Set $0 to pause.</Fine>
      <ExposureCap sup={sup} onSaved={onSaved} />
    </>
  );
}

const CAP_STEP = 100;

/** The most I let Runway have out at once across everyone I support (money already out counts). */
function ExposureCap({ sup, onSaved }: { sup: SupportSummary | null; onSaved: () => void }) {
  const [value, setValue] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const cap = value ?? sup?.exposure_limit ?? 500;
  async function save(next: number) {
    const prev = cap;
    setValue(next);
    setSaving(true);
    try {
      await api.supportExposure(next);
      onSaved();
    } catch {
      setValue(prev);
    } finally {
      setSaving(false);
    }
  }
  return (
    <List style={{ marginTop: 12 }}>
      <Row first left={<Avatar tint={C.cover}><Icon name="shield" size={18} color={C.cover} /></Avatar>}
        title="Most out at once"
        sub={`Across everyone you support · ${money(sup?.committed ?? 0, 0)} out now`}
        right={
          <View style={s.stepper}>
            <Step label="−" disabled={saving || cap <= 0} onPress={() => save(Math.max(0, cap - CAP_STEP))} a11y="Lower the most out at once" />
            <Text style={s.stepValue}>{money(cap, 0)}</Text>
            <Step label="+" disabled={saving || cap >= 5000} onPress={() => save(Math.min(5000, cap + CAP_STEP))} a11y="Raise the most out at once" />
          </View>
        } />
    </List>
  );
}

function Pill({ label, onPress }: { label: string; onPress: () => void }) {
  return (
    <PressableScale onPress={onPress} accessibilityRole="button" style={s.askBtn}>
      <Text style={s.askBtnText}>{label}</Text>
    </PressableScale>
  );
}

function StateDot({ on }: { on: boolean }) {
  return <View style={[s.dot, { backgroundColor: on ? C.green : C.text3 }]} accessibilityLabel={on ? 'Active' : 'Not active'} />;
}

/** Supporter's choice: let Runway move up to my limit, or ask me before every transfer. */
function AskFirst({ a, onChanged }: { a: SupportAgreement; onChanged: () => void }) {
  const [on, setOn] = useState(a.mode === 'approval');
  const [saving, setSaving] = useState(false);
  async function toggle() {
    const next = !on;
    setOn(next);
    setSaving(true);
    try {
      await api.supportMode(a.recipient, next ? 'approval' : 'auto');
      onChanged();
    } catch {
      setOn(!next);
    } finally {
      setSaving(false);
    }
  }
  return (
    <PressableScale onPress={toggle} disabled={saving} accessibilityRole="switch" accessibilityState={{ checked: on }}
      accessibilityLabel="Ask me before every transfer" style={s.switchRow}>
      <View style={{ flex: 1 }}>
        <Text style={s.switchTitle}>Ask me before every transfer</Text>
        <Text style={s.seeText}>{on ? 'On: nothing moves until you approve it.' : 'Off: Runway may move up to your limit when it’s safe for you.'}</Text>
      </View>
      <View style={[s.track, on && s.trackOn, saving && { opacity: 0.6 }]}><View style={[s.knob, on && s.knobOn]} /></View>
    </PressableScale>
  );
}

/**
 * A Quiet Support Agreement, before you say yes: exactly what the other person will and won't see.
 * Rises from the bottom (the shared Sheet), dims the page so the decision has your full attention.
 */
function ConsentSheet({ a, onClose, onDone }: { a: SupportAgreement | null; onClose: () => void; onDone: () => void }) {
  const [busy, setBusy] = useState<'agree' | 'stop' | null>(null);
  const [failed, setFailed] = useState(false);
  const [shown, setShown] = useState<SupportAgreement | null>(a);
  if (a && a !== shown) setShown(a); // keep the content while the sheet animates out
  const x = a ?? shown;
  const recipient = x?.my_side === 'recipient';
  const them = recipient ? x?.supporter_name : x?.recipient_name;

  async function act(kind: 'agree' | 'stop') {
    if (!x) return;
    setBusy(kind);
    setFailed(false);
    try {
      await (kind === 'agree' ? api.supportConsent(x.supporter, x.recipient) : api.supportRevoke(x.supporter, x.recipient));
      onDone();
    } catch {
      setFailed(true);
    } finally {
      setBusy(null);
    }
  }

  const lines: [boolean, string][] = recipient ? [
    [true, `Runway can cover a short gap before your payday, up to ${them}’s limit — you don’t have to ask`],
    [true, 'It goes back automatically after your next verified payday, only when that’s safe for you'],
    [false, `${them} never sees your balance, income, bills, purchases or why you needed it`],
    [true, 'You can stop this any time'],
  ] : [
    [true, 'Runway only moves up to your limit, and only when your own bills stay covered'],
    [true, 'You see who, how much, and when it’s back'],
    [false, `You won’t see ${them}’s balance, spending, or why`],
    [true, 'Change your limit or pause any time'],
  ];

  return (
    <Sheet open={!!a} onClose={onClose} label="Quiet Support Agreement">
      <View style={s.sheet}>
        <Text style={s.sheetKicker}>Quiet Support Agreement</Text>
        <Text style={s.sheetTitle}>{recipient ? `Let ${them} help you quietly?` : `Support ${them} quietly?`}</Text>
        {x && x.they_agreed && !x.i_agreed && <Text style={s.askBody}>{them} already said yes. It starts when you do.</Text>}
        {x?.state === 'active' && <Text style={s.askBody}>You’ve both agreed — this is active.</Text>}
        <View style={{ gap: 10, marginTop: 14 }}>
          {lines.map(([ok, text]) => (
            <View key={text} style={s.seeRow}>
              <Icon name={ok ? 'check' : 'close'} size={16} color={ok ? C.green : C.text3} />
              <Text style={s.seeText}>{text}</Text>
            </View>
          ))}
        </View>
        {x && !recipient && x.i_agreed && <AskFirst a={x} onChanged={onDone} />}
        {failed && <Text style={[s.askBody, { color: C.red }]}>Couldn’t save that. Please try again.</Text>}
        <View style={s.askBtns}>
          {x?.state === 'active' || x?.i_agreed ? (
            <PressableScale onPress={() => act('stop')} disabled={!!busy} accessibilityRole="button" style={[s.btn, s.no]}>
              <Text style={[s.btnText, { color: C.text2 }]}>{busy === 'stop' ? 'Stopping…' : 'Stop support'}</Text>
            </PressableScale>
          ) : (
            <PressableScale onPress={onClose} disabled={!!busy} accessibilityRole="button" style={[s.btn, s.no]}>
              <Text style={[s.btnText, { color: C.text2 }]}>Not now</Text>
            </PressableScale>
          )}
          {!x?.i_agreed && (
            <PressableScale onPress={() => act('agree')} disabled={!!busy} accessibilityRole="button" style={[s.btn, s.yes, busy && { opacity: 0.7 }]}>
              <Text style={[s.btnText, { color: C.onPrimary }]}>{busy === 'agree' ? 'Saving…' : 'Agree'}</Text>
            </PressableScale>
          )}
        </View>
      </View>
    </Sheet>
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
    <View style={[s.ask, { borderColor: alpha(C.red, '55'), marginTop: 8 }]}>
      <Text style={s.askTitle}>You dip to {money(low.balance, 0)} on {weekdayDate(low.date)}</Text>
      <Text style={s.askBody}>That’s before payday, under the {money(floor, 0)} you keep. People in your circle agreed to cover gaps like this. Runway works out who can safely help, and they only see the amount and when it’s back.</Text>
      {note && <Text style={[s.askBody, { color: C.amber }]}>{plain(note)}</Text>}
      <View style={s.askBtns}>
        <PressableScale onPress={ask} disabled={busy} accessibilityRole="button" style={[s.btn, s.yes, busy && { opacity: 0.7 }]}>
          <Text style={[s.btnText, { color: C.onPrimary }]}>{busy ? 'Arranging…' : 'Cover it with my circle'}</Text>
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
        <Text style={s.askTitle}>What your supporters can see</Text>
      </View>
      <View style={s.seeRow}><Icon name="check" size={16} color={C.green} /><Text style={s.seeText}>How much they covered, and the day it goes back</Text></View>
      <View style={s.seeRow}><Icon name="close" size={16} color={C.text3} /><Text style={s.seeText}>Never your balance, your spending, or what it was for</Text></View>
      <View style={s.seeRow}><Icon name="check" size={16} color={C.green} /><Text style={s.seeText}>You never have to ask: Runway does it for you</Text></View>
      {on !== undefined && (
        <PressableScale onPress={toggle} disabled={saving} accessibilityRole="switch" accessibilityState={{ checked: on }}
          accessibilityLabel="Let my circle cover me" style={s.switchRow}>
          <View style={{ flex: 1 }}>
            <Text style={s.switchTitle}>Let my circle cover me</Text>
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

/** Money with people in my circles, shaped like contact payments for the history list. */
function peoplePayments(ppl: PeopleSummary | null): P2PPayment[] {
  if (!ppl) return [];
  return ppl.payments.map((x) => {
    const inbound = x.to_slug === ppl.persona;
    return { id: x.id, date: x.date, direction: inbound ? 'in' : 'out', contact_id: inbound ? x.from_slug : x.to_slug,
      contact: inbound ? x.from_name : x.to_name, amount: x.amount, memo: x.memo } as P2PPayment;
  });
}

const QUICK_AMOUNTS = [10, 20, 50, 100];
const NOTES = ['🎉 Festival', '🍕 Food', '🏠 Rent', '🎁 Gift'];

/**
 * Send money to, or ask money from, anyone in your circles — any time, for anything. A send is a real
 * Nessie transfer (one per tap); a request waits for them to pay it from their own account.
 */
function SendOrRequest({ ppl, onDone }: { ppl: PeopleSummary | null; onDone: () => void }) {
  const [mode, setMode] = useState<'send' | 'ask'>('send');
  const [to, setTo] = useState<string | null>(null);
  const [amount, setAmount] = useState<number | null>(null);
  const [custom, setCustom] = useState('');
  const [note, setNote] = useState(NOTES[0]);
  const [msg, setMsg] = useState<string | null>(null);
  const people = ppl?.people ?? [];
  if (!people.length) return null;
  const who = people.find((p) => p.slug === to);
  const value = amount ?? (Number(custom) > 0 ? Math.round(Number(custom) * 100) / 100 : null);
  const ready = who && value && value <= 1000 && note.trim();
  return (
    <>
      <SectionLabel>Send or request</SectionLabel>
      <View style={[s.ask, { borderColor: C.line2 }]}>
        <View style={s.chips}>
          {(['send', 'ask'] as const).map((m) => (
            <Pick key={m} on={mode === m} label={m === 'send' ? 'Send' : 'Request'} onPress={() => { setMode(m); setMsg(null); }} />
          ))}
        </View>
        <View style={[s.chips, { marginTop: 12 }]}>
          {people.map((p) => <Pick key={p.slug} on={to === p.slug} label={p.name} onPress={() => { setTo(p.slug); setMsg(null); }} />)}
        </View>
        {who && <Text style={s.fineText}>{who.how}</Text>}
        <View style={[s.chips, { marginTop: 10 }]}>
          {QUICK_AMOUNTS.map((n) => <Pick key={n} on={amount === n} label={money(n, 0)} onPress={() => { setAmount(n); setCustom(''); }} />)}
          <TextInput value={custom} onChangeText={(t) => { setCustom(t.replace(/[^0-9.]/g, '')); setAmount(null); }}
            placeholder="Other $" placeholderTextColor={C.text3} keyboardType="decimal-pad" style={s.custom} accessibilityLabel="Other amount" />
        </View>
        <View style={[s.chips, { marginTop: 10 }]}>
          {NOTES.map((n) => <Pick key={n} on={note === n} label={n} onPress={() => setNote(n)} />)}
        </View>
        {msg && <Text style={s.askBody}>{msg}</Text>}
        {ready ? (
          <View style={[s.askBtns, { justifyContent: 'flex-start' }]}>
            <TwoTap label={mode === 'send' ? `Send ${who.name} ${money(value, 0)}` : `Ask ${who.name} for ${money(value, 0)}`}
              confirm="Tap again to confirm" onPress={async () => {
                try {
                  if (mode === 'send') await api.sendTo(who.slug, value, note);
                  else await api.askFrom(who.slug, value, note);
                  setMsg(mode === 'send' ? `Sent ${money(value, 0)} to ${who.name}.` : `Asked ${who.name} for ${money(value, 0)}. They'll see only the amount and your note.`);
                  setAmount(null);
                  setCustom('');
                  onDone();
                } catch (e) {
                  setMsg(reason(e));
                }
              }} />
          </View>
        ) : (
          <Text style={s.fineText}>Pick a person, an amount and a note.</Text>
        )}
      </View>
    </>
  );
}

/** Requests waiting for my answer: pay from my own account, or decline. */
function AskedYou({ ppl, onDone }: { ppl: PeopleSummary | null; onDone: () => void }) {
  const [note, setNote] = useState<string | null>(null);
  const open = ppl?.asked_me ?? [];
  if (!open.length) return null;
  return (
    <>
      <SectionLabel>Requests for you</SectionLabel>
      <List>
        {open.map((r, i) => (
          <Row key={r.id} first={i === 0} left={<Avatar name={r.from_name} />} title={`${r.from_name} asked for ${money(r.amount, 0)}`}
            sub={`${r.memo} · ${monthDay(r.created)}`}
            right={r.status === 'open' ? (
              <View style={s.owe}>
                <PressableScale onPress={async () => { try { await api.answerAsk(r.id, 'decline'); onDone(); } catch (e) { setNote(reason(e)); } }}
                  accessibilityRole="button" style={[s.askBtn, s.ghostBtn]}>
                  <Text style={[s.askBtnText, { color: C.text }]}>Decline</Text>
                </PressableScale>
                <TwoTap label="Pay" confirm={`Pay ${money(r.amount, 0)}?`} onPress={async () => {
                  try { await api.answerAsk(r.id, 'pay'); onDone(); } catch (e) { setNote(reason(e)); }
                }} />
              </View>
            ) : <Amount>Paying…</Amount>} />
        ))}
      </List>
      {note && <Fine>{note}</Fine>}
    </>
  );
}

/** What I asked people for, and what happened. */
function YouAsked({ ppl }: { ppl: PeopleSummary | null }) {
  const mine = (ppl?.i_asked ?? []).slice(0, 5);
  if (!mine.length) return null;
  const word: Record<string, string> = { open: 'Waiting', settling: 'Paying…', paid: 'Paid', declined: 'Declined', cancelled: 'Cancelled', failed: 'Being checked' };
  return (
    <>
      <SectionLabel>You asked</SectionLabel>
      <List>
        {mine.map((r, i) => (
          <Row key={r.id} first={i === 0} left={<Avatar name={r.to_name} />} title={`${r.to_name} · ${money(r.amount, 0)}`}
            sub={`${r.memo} · ${monthDay(r.created)}`} right={<Amount tone={r.status === 'paid' ? 'green' : undefined}>{word[r.status]}</Amount>} />
        ))}
      </List>
    </>
  );
}

/**
 * Named circles: who's in each one, and how to change that — share an invite link, add someone you're
 * already connected to, accept or decline an invitation, leave, and (for the person who made it) remove
 * people or turn its links off. A circle is only people: it never shows or grants anyone's money.
 */
function MyCirclesManager({ list, ppl, onDone }: { list: CircleView[] | null; ppl: PeopleSummary | null; onDone: () => void }) {
  const [name, setName] = useState('');
  const [note, setNote] = useState<string | null>(null);
  if (!list) return null;
  async function create() {
    if (!name.trim()) return;
    try {
      await api.createCircle(name.trim());
      setName('');
      onDone();
    } catch (e) {
      setNote(reason(e));
    }
  }
  return (
    <>
      <SectionLabel>My circles</SectionLabel>
      {list.map((c) => <CircleCard key={c.id} c={c} ppl={ppl} onDone={onDone} />)}
      <View style={[s.ask, { borderColor: C.line2, marginTop: list.length ? 10 : 0 }]}>
        <Text style={s.switchTitle}>Start a circle</Text>
        <View style={[s.owe, { marginTop: 10 }]}>
          <TextInput value={name} onChangeText={setName} placeholder="Roommates, Family, Trip crew…" placeholderTextColor={C.text3}
            maxLength={40} style={[s.custom, { flex: 1 }]} accessibilityLabel="Circle name" onSubmitEditing={create} />
          <PressableScale onPress={create} accessibilityRole="button" style={s.askBtn}>
            <Text style={s.askBtnText}>Create</Text>
          </PressableScale>
        </View>
        {note && <Text style={s.askBody}>{note}</Text>}
      </View>
    </>
  );
}

function CircleCard({ c, ppl, onDone }: { c: CircleView; ppl: PeopleSummary | null; onDone: () => void }) {
  const session = useSession();
  const [msg, setMsg] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const me = session.mode === 'signed-in' ? session.persona : ppl?.persona;
  const inCircle = new Set(c.members.map((m) => m.slug));
  const canAdd = (ppl?.people ?? []).filter((p) => !inCircle.has(p.slug));

  async function act(action: 'invite' | 'remove' | 'accept' | 'decline' | 'leave', slug?: string, done?: string) {
    setMsg(null);
    try {
      await api.circleAction(c.id, action, slug);
      if (done) setMsg(done);
      onDone();
    } catch (e) {
      setMsg(reason(e));
    }
  }

  async function share() {
    setMsg(null);
    try {
      const { token } = await api.circleLink(c.id);
      const origin = Platform.OS === 'web' && typeof window !== 'undefined' ? window.location.origin : 'https://sixsevenbucksleft.vip';
      const url = `${origin}/join/${token}`;
      if (Platform.OS === 'web' && typeof navigator !== 'undefined' && navigator.clipboard) {
        await navigator.clipboard.writeText(url);
        setMsg(`Link copied — it works for 7 days: ${url}`);
      } else {
        await Share.share({ message: `Join my "${c.name}" circle on Runway: ${url}` });
      }
    } catch (e) {
      setMsg(reason(e, 'Couldn’t make a link right now.'));
    }
  }

  if (c.my_state === 'invited') {
    const by = c.members.find((m) => m.state === 'active')?.name ?? 'Someone';
    return (
      <View style={[s.ask, { marginBottom: 10 }]}>
        <Text style={s.askTitle}>{by} invited you to {c.name}</Text>
        <Text style={s.askBody}>A circle shares names only — never anyone’s money.</Text>
        <View style={s.askBtns}>
          <PressableScale onPress={() => act('decline')} accessibilityRole="button" style={[s.btn, s.no]}>
            <Text style={[s.btnText, { color: C.text2 }]}>Decline</Text>
          </PressableScale>
          <PressableScale onPress={() => act('accept')} accessibilityRole="button" style={[s.btn, s.yes]}>
            <Text style={[s.btnText, { color: C.onPrimary }]}>Join</Text>
          </PressableScale>
        </View>
        {msg && <Text style={s.askBody}>{msg}</Text>}
      </View>
    );
  }

  return (
    <View style={[s.mapCard, { marginTop: 0, marginBottom: 10 }]}>
      <View style={s.mapHead}>
        <Text style={s.askTitle}>{c.name}</Text>
        <Text style={s.fineText}>{c.made_by_me ? 'You made this' : `${c.members.filter((m) => m.state === 'active').length} people`}</Text>
      </View>
      <View style={{ marginTop: 8 }}>
        {c.members.map((m) => (
          <View key={m.slug} style={s.memberRow}>
            <Avatar name={m.name} />
            <Text style={[s.switchTitle, { flex: 1 }]}>{m.slug === me ? `${m.name} (you)` : m.name}</Text>
            {m.state === 'invited' && <Text style={s.fineText}>Invited</Text>}
            {c.made_by_me && m.slug !== me && (
              <TwoTap label="Remove" confirm={`Remove ${m.name}?`} light={false} onPress={() => act('remove', m.slug, `${m.name} was removed.`)} />
            )}
          </View>
        ))}
      </View>
      <View style={[s.chips, { marginTop: 12 }]}>
        <PressableScale onPress={share} accessibilityRole="button" style={s.askBtn}>
          <Text style={s.askBtnText}>Share invite link</Text>
        </PressableScale>
        {canAdd.length > 0 && (
          <PressableScale onPress={() => setAdding(!adding)} accessibilityRole="button" style={[s.askBtn, s.ghostBtn]}>
            <Text style={[s.askBtnText, { color: C.text }]}>{adding ? 'Done' : 'Add someone'}</Text>
          </PressableScale>
        )}
        {c.made_by_me ? (
          <TwoTap label="Turn off links" confirm="Turn off every link?" light={false} onPress={async () => {
            try { await api.circleLinksOff(c.id); setMsg('Old links no longer work.'); onDone(); } catch (e) { setMsg(reason(e)); }
          }} />
        ) : (
          <TwoTap label="Leave" confirm={`Leave ${c.name}?`} light={false} onPress={() => act('leave')} />
        )}
      </View>
      {adding && (
        <View style={[s.chips, { marginTop: 10 }]}>
          {canAdd.map((p) => <Pick key={p.slug} on={false} label={`+ ${p.name}`} onPress={() => act('invite', p.slug, `Invited ${p.name}. They’ll see it in their Circles.`)} />)}
        </View>
      )}
      {msg && <Text style={s.fineText} selectable>{msg}</Text>}
    </View>
  );
}

function Pick({ on, label, onPress }: { on: boolean; label: string; onPress: () => void }) {
  return (
    <PressableScale onPress={onPress} accessibilityRole="button" accessibilityState={{ selected: on }} style={[s.pick, on && s.pickOn]}>
      <Text style={[s.askBtnText, { color: on ? C.onPrimary : C.text }]}>{label}</Text>
    </PressableScale>
  );
}

const DEMO = ['maya', 'jordan', 'sam', 'emma', 'alex'];

/** Demo accounts only: rebuild Maya, Jordan and Sam, and pause automatic help until it's shown live. */
function DemoReset({ onDone }: { onDone: () => void }) {
  const session = useSession();
  const [state, setState] = useState<string | null>(null);
  if (session.mode !== 'signed-in' || !DEMO.includes(session.persona)) return null;
  async function reset() {
    setState('Rebuilding the demo accounts… about a minute.');
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
      <TwoTap label="Reset demo" confirm="Reset all demo accounts?" light={false} onPress={reset} />
      {state && <Text style={[s.fineText, { textAlign: 'center' }]}>{state}</Text>}
    </View>
  );
}

/**
 * Demo 6, for presenting: payday comes today. "Arrives" lands a real paycheck in Nessie and runs the real
 * safe-repayment check; "late" runs the same check without one, so it waits — and says why.
 */
function DemoPayday({ onDone }: { onDone: () => void }) {
  const session = useSession();
  const [lines, setLines] = useState<string[] | null>(null);
  const [busy, setBusy] = useState(false);
  if (session.mode !== 'signed-in' || !DEMO.includes(session.persona)) return null;
  async function run(arrives: boolean) {
    setBusy(true);
    setLines(null);
    try {
      const out = await api.demoPayday(arrives);
      setLines(out.length ? out.map((o) => o.outcome === 'repaid' ? `Paid ${o.lender} back ${money(o.amount, 0)}.` : `${o.lender}'s ${money(o.amount, 0)} waits: ${o.why}`) : ['Nothing to pay back.']);
      onDone();
    } catch (e) {
      setLines([reason(e, 'That didn’t run. Try again.')]);
    } finally {
      setBusy(false);
    }
  }
  return (
    <View style={{ alignItems: 'center', marginTop: 28, gap: 8 }}>
      <Text style={s.fineText}>Demo: bring payday to today</Text>
      <View style={s.owe}>
        <PressableScale onPress={() => run(true)} disabled={busy} accessibilityRole="button" style={s.askBtn}>
          <Text style={s.askBtnText}>{busy ? '…' : 'Payday arrives'}</Text>
        </PressableScale>
        <PressableScale onPress={() => run(false)} disabled={busy} accessibilityRole="button" style={[s.askBtn, s.ghostBtn]}>
          <Text style={[s.askBtnText, { color: C.text }]}>Payday is late</Text>
        </PressableScale>
      </View>
      {lines?.map((l) => <Text key={l} style={[s.fineText, { textAlign: 'center' }]}>{l}</Text>)}
    </View>
  );
}

/** A lender's own limit for one person, with −/+. Shows the new value at once; puts it back if the server says no. */
function LimitRow({ l, a, out, first, onSaved }: { l: SafetyLimit; a?: SupportAgreement; out?: Bridge; first: boolean; onSaved: () => void }) {
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
      sub={failed ? 'Couldn’t save. Try again.' : value === 0 ? 'Paused' : out ? `${money(out.amount, 0)} with them now · expected back ${weekdayDate(out.due_date)}` : a ? agreementLine(a) : 'Nothing out'}
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
              <Text style={[s.btnText, { color: C.onPrimary }]}>{busy ? 'Sending…' : `Approve ${money(b.amount, 0)}`}</Text>
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
      <SectionLabel>Support & repayments</SectionLabel>
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
  bridge_approved: ['check', C.green],
  repaid: ['check', C.green],
  approval_needed: ['shield', C.amber],
  partially_covered: ['shield', C.amber],
  bridge_checking: ['transfer', C.amber], // the bank left the outcome unclear: being confirmed
  repay_late: ['transfer', C.amber],
  bridge_failed: ['close', C.red],
  bridge_declined: ['close', C.text2],
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
  cols: { flexDirection: 'row', gap: 24, alignItems: 'flex-start' },
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
  ask: { borderRadius: 20, backgroundColor: C.card, padding: 16, borderWidth: 1, borderColor: alpha(C.amber, '55') },
  askTitle: { fontFamily: F.bodySemi, fontSize: 17, color: C.text },
  askBody: { fontFamily: F.body, fontSize: 14, lineHeight: 20, color: C.text2, marginTop: 4 },
  askBtns: { flexDirection: 'row', gap: 10, marginTop: 14 },
  btn: { flex: 1, height: 46, borderRadius: 999, alignItems: 'center', justifyContent: 'center' },
  no: { borderWidth: 1, borderColor: C.line2 },
  yes: { backgroundColor: C.primary },
  btnText: { fontFamily: F.bodySemi, fontSize: 15 },
  owe: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  askBtn: { height: 32, paddingHorizontal: 14, borderRadius: 999, backgroundColor: C.primary, justifyContent: 'center' },
  askBtnText: { fontFamily: F.bodySemi, fontSize: 13, color: C.onPrimary },
  ghostBtn: { backgroundColor: 'transparent', borderWidth: 1, borderColor: C.line2 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  pick: { height: 36, paddingHorizontal: 16, borderRadius: 999, borderWidth: 1, borderColor: C.line2, justifyContent: 'center' },
  pickOn: { backgroundColor: C.primary, borderColor: C.primary },
  fineText: { fontFamily: F.body, fontSize: 13, lineHeight: 18, color: C.text2, marginTop: 8 },
  custom: { height: 36, minWidth: 90, paddingHorizontal: 14, borderRadius: 999, borderWidth: 1, borderColor: C.line2, color: C.text, fontFamily: F.bodySemi, fontSize: 13 },
  dot: { width: 10, height: 10, borderRadius: 5, marginRight: 6 },
  memberRow: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 6 },
  sheet: { padding: 22, paddingBottom: 26 },
  mapCard: { marginTop: 18, borderRadius: 24, backgroundColor: C.card, padding: 16, paddingBottom: 14 },
  mapHead: { flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between' },
  picked: { flexDirection: 'row', alignItems: 'center', gap: 12, marginTop: 12, paddingTop: 12, borderTopWidth: 1, borderTopColor: C.line },
  sheetKicker: { fontFamily: F.condBold, fontSize: 12, letterSpacing: 1.6, textTransform: 'uppercase', color: C.green },
  sheetTitle: { fontFamily: F.bodySemi, fontSize: 22, lineHeight: 27, letterSpacing: -0.3, color: C.text, marginTop: 6 },
});

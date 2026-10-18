/**
 * The approval sheet: an agent-proposed money move, laid out as plain facts (from, to, when, your
 * lowest point after), with Not now / Approve. The agent never moves money itself: nothing happens
 * until the user taps Approve, which calls POST /actions/{id}/approve.
 * Mounted once in the root layout; any screen opens it with `openApproval`.
 * Outcomes follow the backend contract (as in approval-card.tsx): 503 = nothing moved (retry is safe),
 * 502 = outcome unknown (never offer a retry), 409 = already handled.
 */
import { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { C, F } from '@/constants/runway';
import { httpStatus } from '@/hooks/use-load';
import { api } from '@/lib/api';
import { type ApprovalRequest, getStore, setStore, useStore, moneyMoved } from '@/lib/store';

import { Icon } from './icons';
import { Sheet } from './sheet';
import { PressableScale, T } from './ui';

type Phase = 'waiting' | 'confirming' | 'retry' | 'checking' | 'handled';

export const openApproval = (req: ApprovalRequest) => setStore({ approval: req });

export function ApprovalSheet() {
  const { approval } = useStore();
  // keep the last request on screen while the sheet slides away
  const [shown, setShown] = useState<ApprovalRequest | null>(approval);
  const [phase, setPhase] = useState<Phase>('waiting');
  if (approval && approval !== shown) {
    setShown(approval);
    setPhase('waiting');
  }

  const close = () => {
    if (phase !== 'confirming') setStore({ approval: null });
  };

  async function approve() {
    if (!shown) return;
    setPhase('confirming');
    try {
      await api.approve(shown.action.id);
      moneyMoved(); // every screen re-fetches the new balances
      // Today re-reads the store: the line moves up, turns green, and the plane takes off
      setStore({ approval: null, approvedAmount: getStore().approvedAmount + (shown.action.amount ?? 0), celebrate: true });
    } catch (e) {
      const code = httpStatus(e instanceof Error ? e.message : '');
      setPhase(code === 502 ? 'checking' : code === 409 ? 'handled' : 'retry');
    }
  }

  const note = phase === 'retry' ? 'The bank didn’t accept it. Nothing moved, so it’s safe to try again.'
    : phase === 'checking' ? 'The transfer may not have finished. Don’t try again: we’re checking with the bank.'
    : phase === 'handled' ? 'This was already approved or declined.'
    : 'Nothing moves until you approve.';
  const done = phase === 'checking' || phase === 'handled';

  return (
    <Sheet open={!!approval} onClose={close} label={shown?.title ?? 'Approve a transfer'}>
      {shown && (
        <View>
          <Text style={s.title}>{shown.title}</Text>
          <T tone="dim" style={s.lead}>{shown.lead}</T>
          <View style={s.facts}>
            {shown.facts.map(([k, v], i) => (
              <View key={k} style={[s.fact, i > 0 && s.factLine]}>
                <T tone="dim" style={s.factK}>{k}</T>
                <Text style={s.factV}>{v}</Text>
              </View>
            ))}
          </View>
          <View style={s.safe}>
            <Icon name="shield" size={16} color={phase === 'retry' || phase === 'checking' ? C.amber : C.text2} />
            <T tone="dim" style={{ fontSize: 13, flex: 1 }}>{note}</T>
          </View>
          <View style={s.btns}>
            <PressableScale onPress={close} disabled={phase === 'confirming'} accessibilityRole="button" style={[s.btn, s.no]}>
              <Text style={[s.btnText, { color: C.text2 }]}>{done ? 'Close' : 'Not now'}</Text>
            </PressableScale>
            {!done && (
              <PressableScale onPress={approve} disabled={phase === 'confirming'} accessibilityRole="button"
                style={[s.btn, s.yes, phase === 'confirming' && { opacity: 0.7 }]}>
                <Text style={[s.btnText, { color: C.onPrimary }]}>{phase === 'confirming' ? 'Confirming…' : phase === 'retry' ? 'Try again' : 'Approve'}</Text>
              </PressableScale>
            )}
          </View>
        </View>
      )}
    </Sheet>
  );
}

const s = StyleSheet.create({
  title: { fontFamily: F.bodySemi, fontSize: 22, color: C.text, letterSpacing: -0.2 },
  lead: { fontSize: 15, marginTop: 4 },
  facts: { marginTop: 16, borderRadius: 16, backgroundColor: C.card2, paddingHorizontal: 14 },
  fact: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: 12, paddingVertical: 11 },
  factLine: { borderTopWidth: 1, borderTopColor: C.line2 },
  factK: { fontSize: 15 },
  factV: { fontFamily: F.bodySemi, fontSize: 15, color: C.text, flexShrink: 1, textAlign: 'right' },
  safe: { flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: 14 },
  btns: { flexDirection: 'row', gap: 10, marginTop: 16 },
  btn: { flex: 1, height: 52, borderRadius: 999, alignItems: 'center', justifyContent: 'center' },
  no: { borderWidth: 1, borderColor: C.line2 },
  yes: { backgroundColor: C.primary },
  btnText: { fontFamily: F.bodySemi, fontSize: 16 },
});

// Circle notifications as a pop-up on any screen: "Sam added you to Family" with Join / Decline, and the
// other end's answer ("Maya joined Family"). Refreshes with everything else (lib/store auto-refresh), so
// it appears within ~30 s of the other person acting. Names and the circle only — never money.
import { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import Animated, { FadeInUp, FadeOutUp } from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Icon } from '@/components/rw/icons';
import { PressableScale } from '@/components/rw/ui';
import { C, F } from '@/constants/runway';
import { useLoad } from '@/hooks/use-load';
import { api } from '@/lib/api';
import { moneyMoved, useStore } from '@/lib/store';
import type { InboxItem } from '@/lib/types';

export function InboxPopup() {
  const version = String(useStore().dataVersion);
  const inbox = useLoad(() => api.inbox(), version);
  const [gone, setGone] = useState<string[]>([]); // hidden at once on tap, before the server confirms
  const insets = useSafeAreaInsets();
  const note = (inbox.data ?? []).find((n) => !gone.includes(n.id));
  if (!note) return null;
  return (
    <View pointerEvents="box-none" style={[s.wrap, { top: insets.top + 10 }]}>
      <Card key={note.id} note={note} more={(inbox.data ?? []).filter((n) => !gone.includes(n.id)).length - 1}
        onGone={() => setGone((g) => [...g, note.id])} />
    </View>
  );
}

function Card({ note, more, onGone }: { note: InboxItem; more: number; onGone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const invite = note.kind === 'circle_invite';

  async function answer(action: 'accept' | 'decline') {
    setBusy(true);
    setError(null);
    try {
      await api.circleAction(note.circle_id, action);
      await api.inboxSeen(note.id);
      onGone();
      moneyMoved(); // Circles, the map switcher and Send/Request pick up the new circle
    } catch {
      setError('That didn’t go through. Try again, or answer in Circles.');
      setBusy(false);
    }
  }

  async function dismiss() {
    onGone();
    try {
      await api.inboxSeen(note.id);
    } catch {
      // shown again on the next refresh: harmless
    }
  }

  return (
    <Animated.View entering={FadeInUp.duration(260)} exiting={FadeOutUp.duration(180)} style={s.card}
      accessibilityRole="alert" accessibilityLiveRegion="polite">
      <View style={s.row}>
        <View style={[s.badge, { backgroundColor: invite ? `${C.green}22` : `${C.blue}22` }]}>
          <Icon name={invite ? 'shield' : 'check'} size={18} color={invite ? C.green : C.blue} />
        </View>
        <View style={{ flex: 1 }}>
          <Text style={s.title}>{note.text}</Text>
          <Text style={s.sub}>
            {invite ? 'A circle shares names only — never anyone’s money.' : 'You can see them in Circles.'}
            {more > 0 ? ` · ${more} more` : ''}
          </Text>
        </View>
        {!invite && (
          <PressableScale onPress={dismiss} accessibilityRole="button" accessibilityLabel="Dismiss" style={s.close}>
            <Icon name="close" size={16} color={C.text2} />
          </PressableScale>
        )}
      </View>
      {invite && (
        <View style={s.btns}>
          <PressableScale onPress={() => answer('decline')} disabled={busy} accessibilityRole="button" style={[s.btn, s.ghost]}>
            <Text style={[s.btnText, { color: C.text }]}>Decline</Text>
          </PressableScale>
          <PressableScale onPress={() => answer('accept')} disabled={busy} accessibilityRole="button" style={[s.btn, s.join]}>
            <Text style={s.btnText}>{busy ? '…' : `Join ${note.circle}`}</Text>
          </PressableScale>
        </View>
      )}
      {error && <Text style={[s.sub, { color: C.red, marginTop: 8 }]}>{error}</Text>}
    </Animated.View>
  );
}

const s = StyleSheet.create({
  wrap: { position: 'absolute', left: 12, right: 12, alignItems: 'center', zIndex: 50 },
  card: {
    width: '100%', maxWidth: 440, borderRadius: 20, padding: 14, backgroundColor: C.card2,
    borderWidth: 1, borderColor: '#343c42', shadowColor: '#000', shadowOpacity: 0.35, shadowRadius: 18, shadowOffset: { width: 0, height: 8 },
    elevation: 8,
  },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  badge: { width: 36, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center' },
  title: { fontFamily: F.bodySemi, fontSize: 15, color: C.text },
  sub: { fontFamily: F.body, fontSize: 13, lineHeight: 18, color: C.text2, marginTop: 2 },
  close: { width: 32, height: 32, borderRadius: 16, alignItems: 'center', justifyContent: 'center' },
  btns: { flexDirection: 'row', gap: 8, marginTop: 12 },
  btn: { flex: 1, height: 40, borderRadius: 999, alignItems: 'center', justifyContent: 'center' },
  ghost: { borderWidth: 1, borderColor: '#3a4248' },
  join: { backgroundColor: '#fff' },
  btnText: { fontFamily: F.bodySemi, fontSize: 14, color: '#111' },
});

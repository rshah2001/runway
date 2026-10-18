// An invite link: <site>/join/<token>. Shows which circle it's for and who made it, then joins on a tap.
// Signed out, the login screen shows first and brings you back here (lib/auth.ts AFTER_KEY).
// Joining grants nothing financial — support still needs an agreement between two people.
import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { PageTitle, TopBar } from '@/components/rw/top-bar';
import { LoadState, Page, PressableScale } from '@/components/rw/ui';
import { C, F } from '@/constants/runway';
import { useLoad } from '@/hooks/use-load';
import { api } from '@/lib/api';
import { moneyMoved } from '@/lib/store';

export default function JoinScreen() {
  const { token } = useLocalSearchParams<{ token: string }>();
  const preview = useLoad(() => api.joinPreview(String(token)), String(token));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const p = preview.data;

  async function join() {
    setBusy(true);
    setError(null);
    try {
      await api.joinCircle(String(token));
      moneyMoved();
      router.replace('/circles');
    } catch (e) {
      setError(e instanceof Error && e.message.includes('403') ? 'This invitation can’t be used — ask for a new one.' : 'That didn’t work. Try again.');
      setBusy(false);
    }
  }

  return (
    <Page>
      <TopBar />
      <PageTitle title="Circle invitation" sub="Joining a circle shares nothing about your money." />
      {!p ? <View style={{ marginTop: 24 }}><LoadState error={preview.error ? 'This invite link has expired or been turned off. Ask for a new one.' : null} onRetry={preview.reload} /></View> : (
        <View style={s.card}>
          <Text style={s.title}>{p.already_in ? `You’re already in ${p.name}` : `Join ${p.name}?`}</Text>
          <Text style={s.body}>{p.made_by}’s circle. People in it can send to and ask each other. Covering a gap still needs an agreement you both say yes to.</Text>
          {error && <Text style={[s.body, { color: C.red }]}>{error}</Text>}
          <PressableScale onPress={p.already_in ? () => router.replace('/circles') : join} disabled={busy} accessibilityRole="button" style={s.btn}>
            <Text style={s.btnText}>{p.already_in ? 'Open Circles' : busy ? 'Joining…' : `Join ${p.name}`}</Text>
          </PressableScale>
        </View>
      )}
    </Page>
  );
}

const s = StyleSheet.create({
  card: { marginTop: 18, borderRadius: 20, backgroundColor: C.card, padding: 20, gap: 10 },
  title: { fontFamily: F.bodySemi, fontSize: 22, color: C.text, letterSpacing: -0.3 },
  body: { fontFamily: F.body, fontSize: 15, lineHeight: 21, color: C.text2 },
  btn: { marginTop: 8, height: 48, borderRadius: 999, backgroundColor: C.primary, alignItems: 'center', justifyContent: 'center' },
  btnText: { fontFamily: F.bodySemi, fontSize: 16, color: C.onPrimary },
});

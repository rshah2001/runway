/** A quiet, focused entry point. Account access first; demo choices on request. */
import { useState } from 'react';
import { ActivityIndicator, Platform, Pressable, ScrollView, StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Icon, Swoosh } from '@/components/rw/icons';
import { F } from '@/constants/runway';
import { useLoad } from '@/hooks/use-load';
import { enterAsGuest, enterSignedIn, NotLinked, signIn } from '@/lib/account';
import { api } from '@/lib/api';
import { isAuthConfigured } from '@/lib/auth';
import type { Persona } from '@/lib/types';

const INK = '#202522';
const SECONDARY = '#737a75';

export function LoginScreen() {
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();
  const [showDemos, setShowDemos] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSignIn() {
    setBusy(true);
    setError(null);
    try {
      const profile = await signIn();
      if (profile) enterSignedIn(profile);
      else setBusy(false);
    } catch (e) {
      setBusy(false);
      setError(e instanceof NotLinked ? e.message : 'Sign-in didn’t finish. Please try again.');
    }
  }

  return (
    <View style={s.page}>
      <ScrollView contentContainerStyle={[s.scroll, { paddingTop: Platform.OS === 'web' ? 0 : insets.top, paddingBottom: insets.bottom }]}>
        <View style={s.header}>
          <View style={s.brand}><Swoosh size={24} color={INK} /><Text style={s.wordmark}>runway</Text></View>
        </View>

        <View style={s.main}>
          <View style={s.content}>
            <View style={s.mark} accessible={false}><Swoosh size={43} color={INK} /></View>
            <Text accessibilityRole="header" style={[s.headline, width < 440 && s.headlineSmall]}>Your money.{ '\n' }A clearer tomorrow.</Text>
            <Text style={s.description}>Know what’s ahead.{ '\n' }Feel good about what’s next.</Text>
            <View style={s.actions}>
              <Pressable onPress={onSignIn} disabled={busy || !isAuthConfigured} accessibilityRole="button" accessibilityState={{ disabled: busy || !isAuthConfigured, busy }}
                style={({ hovered, pressed }) => [s.primary, hovered && s.primaryHover, pressed && s.pressed, (busy || !isAuthConfigured) && s.disabled]}>
                {busy ? <ActivityIndicator color="#fff" /> : <Text style={s.primaryText}>Sign in to Runway</Text>}
              </Pressable>
              {!isAuthConfigured && <Text style={s.previewNote}>Sign-in is unavailable in this local preview.</Text>}
              {error && <Text style={s.error} accessibilityRole="alert" accessibilityLiveRegion="polite">{error}</Text>}
              <Pressable onPress={() => setShowDemos(!showDemos)} disabled={busy} accessibilityRole="button" accessibilityState={{ expanded: showDemos, disabled: busy }}
                style={({ hovered, pressed }) => [s.secondary, hovered && s.secondaryHover, pressed && s.pressed]}>
                <Text style={s.secondaryText}>{showDemos ? 'Close demo accounts' : 'Explore a demo'}</Text>
                <Text style={s.arrow}>{showDemos ? '−' : '→'}</Text>
              </Pressable>
              {showDemos && <DemoAccounts disabled={busy} />}
            </View>
            {isAuthConfigured && <View style={s.security}><Icon name="shield" size={13} color={SECONDARY} /><Text style={s.securityText}>Secure sign-in with Auth0</Text></View>}
          </View>
        </View>

        <View style={s.footer}><Text style={s.footerText}>A little foresight goes a long way.</Text></View>
      </ScrollView>
    </View>
  );
}

function DemoAccounts({ disabled }: { disabled: boolean }) {
  const people = useLoad(() => api.personas());
  const ordered = [...(people.data ?? [])].sort((a, b) => a.age - b.age);
  function enter(p: Persona) {
    enterAsGuest({ persona: p.slug, name: p.first_name });
  }
  return (
    <View style={s.demos}>
      <Text style={s.demoIntro}>A look inside. No account needed.</Text>
      {people.error ? (
        <View style={s.loadState}>
          <Text style={s.demoIntro} accessibilityLiveRegion="polite">Demo accounts couldn’t load.</Text>
          <Pressable onPress={people.reload} disabled={people.loading} accessibilityRole="button" style={s.secondary}><Text style={s.secondaryText}>{people.loading ? 'Loading…' : 'Try again'}</Text></Pressable>
        </View>
      ) : !people.data ? (
        <ActivityIndicator color={INK} style={s.loadState} accessibilityLabel="Loading demo accounts" />
      ) : ordered.length === 0 ? <Text style={s.demoIntro}>No demo accounts are available yet.</Text> : ordered.map((p) => (
        <Pressable key={p.slug} onPress={() => enter(p)} disabled={disabled} accessibilityRole="button" accessibilityLabel={`Explore as ${p.first_name}, age ${p.age}. ${p.story}`} accessibilityState={{ disabled }}
          style={({ hovered, pressed }) => [s.person, hovered && s.personHover, pressed && s.pressed]}>
          <View style={s.personCopy}><Text style={s.personName}>{p.first_name}<Text style={s.personAge}> · {p.age}</Text></Text><Text style={s.personStory}>{p.story}</Text></View>
          <Text style={s.personArrow}>→</Text>
        </Pressable>
      ))}
      <Text style={s.demoFootnote}>Demo accounts use fictional customer data.</Text>
    </View>
  );
}

const s = StyleSheet.create({
  page: { flex: 1, backgroundColor: '#fafbf9' },
  scroll: { flexGrow: 1 },
  header: { width: '100%', maxWidth: 1440, alignSelf: 'center', paddingHorizontal: 32, paddingVertical: 29 },
  brand: { flexDirection: 'row', alignItems: 'center', gap: 9 },
  wordmark: { fontFamily: F.bodySemi, color: INK, fontSize: 25, letterSpacing: -0.9 },
  main: { flex: 1, justifyContent: 'center', alignItems: 'center', paddingHorizontal: 24, paddingTop: 42, paddingBottom: 72 },
  content: { width: '100%', maxWidth: 420, alignItems: 'center' },
  mark: { width: 78, height: 78, borderRadius: 24, backgroundColor: '#edf1ec', alignItems: 'center', justifyContent: 'center', marginBottom: 34 },
  headline: { fontFamily: F.bodySemi, fontSize: 43, lineHeight: 49, letterSpacing: -1.7, color: INK, textAlign: 'center' },
  headlineSmall: { fontSize: 34, lineHeight: 40, letterSpacing: -1.3 },
  description: { fontFamily: F.body, fontSize: 17, lineHeight: 25, color: SECONDARY, textAlign: 'center', marginTop: 20 },
  actions: { width: '100%', maxWidth: 320, marginTop: 38 },
  primary: { minHeight: 52, backgroundColor: INK, borderRadius: 12, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 20 },
  primaryHover: { backgroundColor: '#39423c' },
  primaryText: { fontFamily: F.bodyMedium, fontSize: 16, color: '#fff' },
  disabled: { opacity: 0.45 },
  pressed: { opacity: 0.7 },
  secondary: { minHeight: 48, paddingHorizontal: 14, marginTop: 8, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 9, borderRadius: 10 },
  secondaryHover: { backgroundColor: '#eff2ed' },
  secondaryText: { fontFamily: F.bodyMedium, color: INK, fontSize: 14 },
  arrow: { color: INK, fontSize: 18 },
  previewNote: { fontFamily: F.body, color: SECONDARY, fontSize: 12, textAlign: 'center', marginTop: 10 },
  error: { fontFamily: F.body, color: '#a3302e', fontSize: 13, lineHeight: 19, textAlign: 'center', marginTop: 14 },
  security: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 28 },
  securityText: { fontFamily: F.body, color: SECONDARY, fontSize: 11 },
  demos: { borderTopWidth: 1, borderTopColor: '#dfe4de', marginTop: 16, paddingTop: 22 },
  demoIntro: { fontFamily: F.body, fontSize: 12, lineHeight: 18, color: SECONDARY, textAlign: 'center', marginBottom: 14 },
  loadState: { paddingVertical: 20 },
  person: { flexDirection: 'row', alignItems: 'center', gap: 14, paddingVertical: 14, paddingHorizontal: 12, borderRadius: 10 },
  personHover: { backgroundColor: '#edf1eb' },
  personCopy: { flex: 1 },
  personName: { fontFamily: F.bodySemi, fontSize: 15, color: INK },
  personAge: { fontFamily: F.body, color: SECONDARY },
  personStory: { fontFamily: F.body, fontSize: 12, lineHeight: 17, color: SECONDARY, marginTop: 4 },
  personArrow: { color: SECONDARY, fontSize: 19 },
  demoFootnote: { fontFamily: F.body, fontSize: 10, color: SECONDARY, textAlign: 'center', marginTop: 16 },
  footer: { alignItems: 'center', paddingBottom: 25, paddingHorizontal: 24 },
  footerText: { fontFamily: F.body, color: '#848b85', fontSize: 11 },
});

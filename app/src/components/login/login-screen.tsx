/**
 * The way in. Two paths, in order of importance: sign in with Auth0, or look around as one of the
 * three demo customers (Maya 20, Jordan 40, Sam 60) — the same data, no account needed.
 *
 * The one memorable moment: the hero is Maya's real runway, drawn from the live forecast, and
 * choosing a way in plays the plane's takeoff before the app opens. Motion answers the person's
 * action; with reduced motion the app opens immediately.
 */
import { useState } from 'react';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';
import { useReducedMotion } from 'react-native-reanimated';

import { Swoosh } from '@/components/rw/icons';
import { RunwayStrip } from '@/components/rw/runway-strip';
import { Btn, Card, Page, PressableScale, T, useWide } from '@/components/rw/ui';
import { C, F, RADIUS } from '@/constants/runway';
import { useLoad } from '@/hooks/use-load';
import { enterAsGuest, enterSignedIn, NotLinked, type Profile, signIn } from '@/lib/account';
import { api } from '@/lib/api';
import { isAuthConfigured } from '@/lib/auth';
import { monthDay } from '@/lib/format';
import { isClear, runwayDays } from '@/lib/runway';
import type { Persona } from '@/lib/types';

const TAKEOFF_MS = 1500; // the strip's takeoff: 380ms delay + 1100ms climb

export function LoginScreen() {
  const wide = useWide();
  const reduced = useReducedMotion();
  const people = useLoad(() => api.personas());
  const [takeoffKey, setTakeoffKey] = useState(0);
  const [busy, setBusy] = useState<string | null>(null); // 'signin' or a persona slug
  const [error, setError] = useState<string | null>(null);

  /** Play the takeoff, then let the app replace this screen. */
  function takeOff(enter: () => void) {
    setTakeoffKey((k) => k + 1);
    setTimeout(enter, reduced ? 0 : TAKEOFF_MS);
  }

  async function onSignIn() {
    setBusy('signin');
    setError(null);
    try {
      const profile = await signIn();
      if (!profile) {
        setBusy(null); // closed the Auth0 window: nothing to say
        return;
      }
      takeOff(() => enterSignedIn(profile));
    } catch (e) {
      setBusy(null);
      setError(e instanceof NotLinked ? e.message : 'Sign-in didn’t finish. Check your connection and try again.');
    }
  }

  function onGuest(p: Persona) {
    setBusy(p.slug);
    setError(null);
    const profile: Profile = { persona: p.slug, name: p.first_name };
    takeOff(() => enterAsGuest(profile));
  }

  const ordered = [...(people.data ?? [])].sort((a, b) => a.age - b.age);

  const hero = (
    <View style={[s.hero, wide && s.heroWide]}>
      <View style={s.brand}>
        <Swoosh size={26} />
        <Text style={s.wordmark}>Runway</Text>
      </View>
      <Text style={[s.headline, wide && s.headlineWide]} accessibilityRole="header">
        See the day you’d run short, before it happens.
      </Text>
      <T tone="dim" style={s.lede}>
        Runway forecasts your checking balance day by day, and covers a dip with your own savings or
        family who agreed to help — before an overdraft fee ever lands.
      </T>
      <HeroRunway takeoffKey={takeoffKey} />
    </View>
  );

  const panel = (
    <View style={[s.panel, wide && s.panelWide]}>
      <Card style={s.signInCard}>
        <Text style={s.panelTitle}>Sign in</Text>
        {isAuthConfigured ? (
          <>
            <T tone="dim" style={s.small}>Your forecast, your money, only you. Auth0 handles your password; Runway never sees it.</T>
            <Btn label={busy === 'signin' ? 'Opening Auth0…' : 'Continue with Auth0'} onPress={onSignIn} disabled={busy !== null} style={s.primary} />
          </>
        ) : (
          <T tone="dim" style={s.small}>Sign-in isn’t switched on yet. Look around as a demo customer below.</T>
        )}
        {error && (
          <T tone="red" style={s.small} accessibilityLiveRegion="polite">
            {error}
          </T>
        )}
      </Card>

      <Text style={s.or}>Or look around as one of our demo customers</Text>
      {people.error ? (
        <T tone="dim" style={s.small}>Can’t reach Runway right now. Check your connection and refresh.</T>
      ) : !people.data ? (
        <ActivityIndicator color={C.text2} style={{ marginVertical: 18 }} />
      ) : (
        <View style={s.people}>
          {ordered.map((p) => (
            <PersonRow key={p.slug} p={p} busy={busy} wide={wide} onPress={() => onGuest(p)} />
          ))}
        </View>
      )}
      <T tone="faint" style={s.footnote}>
        Demo customers are fictional. Their balances and history come from Capital One’s Nessie API.
      </T>
    </View>
  );

  return (
    <Page>
      <View style={[s.wrap, wide && s.wrapWide]}>
        {hero}
        {panel}
      </View>
    </Page>
  );
}

/** Maya's real runway right now — the product, shown instead of described. */
function HeroRunway({ takeoffKey }: { takeoffKey: number }) {
  const f = useLoad(() => api.forecast(30, 'maya'));
  if (!f.data) return <View style={s.stripSpace} />;
  const days = runwayDays(f.data), horizon = f.data.points.length - 1;
  return (
    <View style={s.stripCard}>
      <T tone="dim" style={s.stripCaption}>
        {isClear(f.data) ? 'Maya is covered all month' : `Maya runs short in ${days} days — Runway can see it coming`}
      </T>
      <RunwayStrip
        days={days}
        horizon={horizon}
        endLabel={days < horizon ? monthDay(f.data.points[days].date) : ''}
        lastLabel={monthDay(f.data.points[horizon].date)}
        takeoffKey={takeoffKey}
      />
    </View>
  );
}

/** One demo customer, with their live status from the forecast. */
function PersonRow({ p, busy, wide, onPress }: { p: Persona; busy: string | null; wide: boolean; onPress: () => void }) {
  const f = useLoad(() => api.forecast(30, p.slug), p.slug);
  const status = f.data
    ? isClear(f.data)
      ? { text: 'Covered all month', color: C.green }
      : { text: `Runs short ${monthDay(f.data.points[runwayDays(f.data)].date)}`, color: C.red }
    : null;
  const choosing = busy === p.slug;
  return (
    <PressableScale
      onPress={onPress}
      disabled={busy !== null}
      accessibilityRole="button"
      accessibilityLabel={`Look around as ${p.first_name}, ${p.age}. ${p.story}`}
      style={[s.person, choosing && s.personChosen, busy !== null && !choosing && { opacity: 0.5 }]}>
      <View style={s.age}>
        <Text style={s.ageNum}>{p.age}</Text>
      </View>
      <View style={{ flex: 1, gap: 2 }}>
        <Text style={s.personName}>{p.first_name}</Text>
        <T tone="dim" style={s.small} numberOfLines={2}>{p.story}</T>
        {/* phones: the status sits under the story so the story isn't squeezed */}
        {status && !wide && <StatusPill {...status} />}
      </View>
      {status && wide && <StatusPill {...status} />}
    </PressableScale>
  );
}

function StatusPill({ text, color }: { text: string; color: string }) {
  return (
    <View style={[s.status, { borderColor: `${color}66` }]}>
      <View style={[s.dot, { backgroundColor: color }]} />
      <Text style={[s.statusText, { color }]}>{text}</Text>
    </View>
  );
}

const s = StyleSheet.create({
  wrap: { gap: 28, paddingVertical: 12, paddingHorizontal: 8 },
  wrapWide: { flexDirection: 'row', alignItems: 'center', gap: 56, minHeight: 640, paddingVertical: 40 },

  hero: { gap: 16 },
  heroWide: { flex: 1.15 },
  brand: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  wordmark: { fontFamily: F.condBold, fontSize: 24, color: C.text, letterSpacing: 4, textTransform: 'uppercase' },
  // large display type: tight leading, negative tracking
  headline: { fontFamily: F.condBold, fontSize: 42, lineHeight: 43, letterSpacing: -0.6, color: C.text, marginTop: 8 },
  headlineWide: { fontSize: 64, lineHeight: 62, letterSpacing: -1.2 },
  lede: { fontSize: 17, lineHeight: 25, maxWidth: 520 },
  stripCard: { marginTop: 10, paddingVertical: 14, paddingHorizontal: 14, backgroundColor: C.card, borderRadius: RADIUS, borderWidth: 1, borderColor: C.line },
  stripCaption: { fontSize: 14, marginBottom: 6 },
  stripSpace: { height: 128 },

  panel: { gap: 14 },
  panelWide: { flex: 1, maxWidth: 460 },
  signInCard: { gap: 12, padding: 22 },
  panelTitle: { fontFamily: F.condBold, fontSize: 28, color: C.text, letterSpacing: -0.2 },
  small: { fontSize: 14, lineHeight: 20 },
  primary: { alignSelf: 'stretch', marginTop: 4 },
  or: { fontFamily: F.bodyMedium, fontSize: 15, color: C.text2, marginTop: 10, marginLeft: 4 },

  people: { gap: 10 },
  person: {
    flexDirection: 'row', alignItems: 'center', gap: 14, padding: 14,
    backgroundColor: C.card, borderRadius: RADIUS, borderWidth: 1, borderColor: C.line,
  },
  personChosen: { borderColor: C.text2, backgroundColor: C.card2 },
  age: { width: 46, height: 46, borderRadius: 23, backgroundColor: C.card2, alignItems: 'center', justifyContent: 'center' },
  ageNum: { fontFamily: F.condBold, fontSize: 20, color: C.text },
  personName: { fontFamily: F.bodySemi, fontSize: 17, color: C.text },
  status: {
    flexDirection: 'row', alignItems: 'center', alignSelf: 'flex-start', gap: 6, marginTop: 4,
    borderWidth: 1, borderRadius: 999, paddingVertical: 4, paddingHorizontal: 9,
  },
  dot: { width: 7, height: 7, borderRadius: 4 },
  statusText: { fontFamily: F.bodyMedium, fontSize: 12.5 },
  footnote: { fontSize: 12.5, lineHeight: 18, marginTop: 6, marginLeft: 4 },
});

/**
 * The way in: sign in with Auth0 — the only way in, so every view of money belongs to its owner.
 *
 * Motion, in two moments:
 *  - on open, the hairlines go down like runway markings: the centre line under the wordmark
 *    draws across, the words settle, then the sign-in card's border traces itself and the button
 *    arrives last (≈1.5s, once; nothing moves afterwards);
 *  - on sign-in, Maya's real runway plays the plane's takeoff before the app opens.
 * With reduced motion everything starts in place and the app opens immediately.
 */
import { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { useReducedMotion } from 'react-native-reanimated';

import { Swoosh } from '@/components/rw/icons';
import { RunwayStrip } from '@/components/rw/runway-strip';
import { HairlineFrame, HairlineRule, Settle } from '@/components/login/hairline';
import { Btn, Page, T, useWide } from '@/components/rw/ui';
import { C, F, RADIUS } from '@/constants/runway';
import { useLoad } from '@/hooks/use-load';
import { enterSignedIn, NotLinked, signIn } from '@/lib/account';
import { api } from '@/lib/api';
import { isAuthConfigured } from '@/lib/auth';
import { monthDay } from '@/lib/format';
import { isClear, runwayDays } from '@/lib/runway';

const TAKEOFF_MS = 1500; // the strip's takeoff: 380ms delay + 1100ms climb
// the opening sequence, in ms from mount
const OPEN = { rule: 80, words: 260, strip: 420, frame: 520, button: 1250 };

export function LoginScreen() {
  const wide = useWide();
  const reduced = useReducedMotion();
  const [takeoffKey, setTakeoffKey] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /** Play the takeoff, then let the app replace this screen. */
  function takeOff(enter: () => void) {
    setTakeoffKey((k) => k + 1);
    setTimeout(enter, reduced ? 0 : TAKEOFF_MS);
  }

  async function onSignIn() {
    setBusy(true);
    setError(null);
    try {
      const profile = await signIn();
      if (!profile) {
        setBusy(false); // closed the Auth0 window: nothing to say
        return;
      }
      takeOff(() => enterSignedIn(profile));
    } catch (e) {
      setBusy(false);
      setError(e instanceof NotLinked ? e.message : 'Sign-in didn’t finish. Check your connection and try again.');
    }
  }

  const hero = (
    <View style={[s.hero, wide && s.heroWide]}>
      <View style={s.brand}>
        <Swoosh size={26} />
        <Text style={s.wordmark}>Runway</Text>
      </View>
      <HairlineRule delay={OPEN.rule} />
      <Settle delay={OPEN.words} style={s.words}>
        <Text style={[s.headline, wide && s.headlineWide]} accessibilityRole="header">
          See the day you’d run short, before it happens.
        </Text>
        <T tone="dim" style={s.lede}>
          Runway forecasts your checking balance day by day, and covers a dip with your own savings or
          family who agreed to help — before an overdraft fee ever lands.
        </T>
      </Settle>
      <Settle delay={OPEN.strip}>
        <HeroRunway takeoffKey={takeoffKey} />
      </Settle>
    </View>
  );

  const panel = (
    <View style={[s.panel, wide && s.panelWide]}>
      <HairlineFrame delay={OPEN.frame} style={s.signInCard} contentStyle={s.signInContents}>
        <Text style={s.panelTitle}>Sign in</Text>
        {isAuthConfigured ? (
          <>
            <T tone="dim" style={s.small}>Your forecast, your money, only you. Auth0 handles your password; Runway never sees it.</T>
            <Settle delay={OPEN.button}>
              <Btn label={busy ? 'Opening Auth0…' : 'Continue with Auth0'} onPress={onSignIn} disabled={busy} style={s.primary} />
            </Settle>
          </>
        ) : (
          <T tone="dim" style={s.small}>Sign-in isn’t switched on for this build. Set the Auth0 settings and rebuild.</T>
        )}
        {error && (
          <T tone="red" style={s.small} accessibilityLiveRegion="polite">
            {error}
          </T>
        )}
      </HairlineFrame>
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

const s = StyleSheet.create({
  wrap: { gap: 28, paddingVertical: 12, paddingHorizontal: 8 },
  wrapWide: { flexDirection: 'row', alignItems: 'center', gap: 56, minHeight: 640, paddingVertical: 40 },

  hero: { gap: 16 },
  heroWide: { flex: 1.15 },
  brand: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  wordmark: { fontFamily: F.condBold, fontSize: 24, color: C.text, letterSpacing: 4, textTransform: 'uppercase' },
  // large display type: tight leading, negative tracking
  words: { gap: 16 },
  headline: { fontFamily: F.condBold, fontSize: 42, lineHeight: 43, letterSpacing: -0.6, color: C.text },
  headlineWide: { fontSize: 64, lineHeight: 62, letterSpacing: -1.2 },
  lede: { fontSize: 17, lineHeight: 25, maxWidth: 520 },
  stripCard: { marginTop: 10, paddingVertical: 14, paddingHorizontal: 14, backgroundColor: C.card, borderRadius: RADIUS, borderWidth: 1, borderColor: C.line },
  stripCaption: { fontSize: 14, marginBottom: 6 },
  stripSpace: { height: 128 },

  panel: { gap: 14 },
  panelWide: { flex: 1, maxWidth: 460 },
  signInCard: { padding: 22 },
  signInContents: { gap: 12 },
  panelTitle: { fontFamily: F.condBold, fontSize: 28, color: C.text, letterSpacing: -0.2 },
  small: { fontSize: 14, lineHeight: 20 },
  primary: { alignSelf: 'stretch', marginTop: 4 },
});

/**
 * The way in: sign in with Auth0 — the only way in, so every view of money belongs to its owner.
 *
 * One centred column above a hairline runway that runs off to the horizon (see airfield.tsx).
 * Motion happens once, on open: the horizon spreads, the runway draws toward it, the words settle,
 * the button arrives last. Nothing moves afterwards. With reduced motion everything starts in place.
 */
import { type PropsWithChildren, useEffect, useState } from 'react';
import { type StyleProp, StyleSheet, Text, useWindowDimensions, View, type ViewStyle } from 'react-native';
import Animated, { Easing, useAnimatedStyle, useReducedMotion, useSharedValue, withDelay, withTiming } from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Svg, { Defs, LinearGradient, Rect, Stop } from 'react-native-svg';

import { Airfield } from '@/components/login/airfield';
import { Swoosh } from '@/components/rw/icons';
import { PressableScale, T, useWide } from '@/components/rw/ui';
import { C, F } from '@/constants/runway';
import { enterSignedIn, NotLinked, signIn } from '@/lib/account';
import { isAuthConfigured } from '@/lib/auth';

// the opening sequence, in ms from mount (the airfield keeps its own timings)
const OPEN = { brand: 0, words: 350, button: 900 };

export function LoginScreen() {
  const wide = useWide();
  const insets = useSafeAreaInsets();
  const { height } = useWindowDimensions();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSignIn() {
    setBusy(true);
    setError(null);
    try {
      const profile = await signIn();
      if (!profile) {
        setBusy(false); // closed the Auth0 window: nothing to say
        return;
      }
      enterSignedIn(profile);
    } catch (e) {
      setBusy(false);
      setError(e instanceof NotLinked ? e.message : 'Sign-in didn’t finish. Check your connection and try again.');
    }
  }

  const fieldHeight = Math.round(Math.max(150, Math.min(height * 0.34, 340)));

  return (
    <View style={s.root}>
      <Backdrop />
      <View style={[s.column, { paddingTop: insets.top + 24, paddingHorizontal: wide ? 32 : 20 }]}>
        <Settle delay={OPEN.brand} style={s.brand}>
          <Swoosh size={22} />
          <Text style={s.wordmark}>Runway</Text>
        </Settle>

        <Settle delay={OPEN.words} style={s.words}>
          <Text style={[s.headline, wide && s.headlineWide]} accessibilityRole="header">
            See the day you’d run short, before it happens.
          </Text>
          <T tone="dim" style={[s.lede, wide && s.ledeWide]}>
            Runway forecasts your checking balance day by day and covers a dip before an overdraft fee lands.
          </T>
        </Settle>

        <Settle delay={OPEN.button} style={s.action}>
          {isAuthConfigured ? (
            <>
              <PressableScale onPress={onSignIn} disabled={busy} accessibilityRole="button" style={[s.button, !wide && s.buttonPhone, busy && { opacity: 0.6 }]}>
                <Text style={s.buttonText}>{busy ? 'Opening Auth0…' : 'Continue with Auth0'}</Text>
              </PressableScale>
              <T tone="faint" style={s.note}>Auth0 handles your password. Runway never sees it.</T>
            </>
          ) : (
            <T tone="dim" style={s.note}>Sign-in isn’t switched on for this build. Set the Auth0 settings and rebuild.</T>
          )}
          {error && (
            <T tone="red" style={s.note} accessibilityLiveRegion="polite">
              {error}
            </T>
          )}
        </Settle>
      </View>
      <Airfield height={fieldHeight} />
    </View>
  );
}

/** Children that settle in once: a short fade and a 6px rise. */
function Settle({ delay, children, style }: PropsWithChildren<{ delay: number; style?: StyleProp<ViewStyle> }>) {
  const reduced = useReducedMotion();
  const p = useSharedValue(reduced ? 1 : 0);
  useEffect(() => {
    if (reduced) p.set(1);
    else p.set(withDelay(delay, withTiming(1, { duration: 480, easing: Easing.bezier(0.23, 1, 0.32, 1) })));
  }, [reduced, delay, p]);
  const anim = useAnimatedStyle(() => ({ opacity: p.get(), transform: [{ translateY: (1 - p.get()) * 6 }] }));
  return <Animated.View style={[style, anim]}>{children}</Animated.View>;
}

/** Night sky over the field: lighter at the top, darkest at the horizon. */
function Backdrop() {
  return (
    <Svg style={StyleSheet.absoluteFill} preserveAspectRatio="none" viewBox="0 0 100 100" pointerEvents="none">
      <Defs>
        <LinearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
          <Stop offset="0" stopColor={C.bgTop} />
          <Stop offset="0.66" stopColor={C.bg} />
          <Stop offset="1" stopColor="#101317" />
        </LinearGradient>
      </Defs>
      <Rect width="100" height="100" fill="url(#sky)" />
    </Svg>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: C.bg },
  column: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 28, paddingBottom: 24 },

  brand: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  wordmark: { fontFamily: F.condBold, fontSize: 20, color: C.text, letterSpacing: 5, textTransform: 'uppercase' },

  words: { alignItems: 'center', gap: 14 },
  // large display type: tight leading, negative tracking
  headline: { fontFamily: F.condBold, fontSize: 40, lineHeight: 42, letterSpacing: -0.6, color: C.text, textAlign: 'center', maxWidth: 520 },
  headlineWide: { fontSize: 68, lineHeight: 66, letterSpacing: -1.4, maxWidth: 760 },
  lede: { fontSize: 16, lineHeight: 24, textAlign: 'center', maxWidth: 420 },
  ledeWide: { fontSize: 18, lineHeight: 27, maxWidth: 520 },

  action: { alignItems: 'center', gap: 12, alignSelf: 'stretch' },
  button: {
    width: 320, height: 52, borderRadius: 26, backgroundColor: '#fff',
    alignItems: 'center', justifyContent: 'center',
  },
  buttonPhone: { width: '100%', maxWidth: 360 },
  buttonText: { fontFamily: F.bodySemi, fontSize: 16, color: '#111', letterSpacing: 0.1 },
  note: { fontSize: 13, lineHeight: 19, textAlign: 'center' },
});

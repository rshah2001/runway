/**
 * The way in: sign in with Auth0 — the only way in, so every view of money belongs to its owner.
 *
 * One centred column above a hairline runway that runs off to the horizon (see airfield.tsx).
 *
 * Motion (Apple's rules: critically damped springs, feedback on press-down, motion that answers
 * the person; reduced motion → everything in place and the app opens straight away):
 *  - open, once: the field draws itself, then the brand, words and button settle in on springs;
 *  - pointer: the runway's vanishing point follows the cursor a little, on a spring (website);
 *  - the button lifts under the pointer and presses in on touch-down;
 *  - sign-in: the words lift away, the plane rolls up the centre line into the horizon, the app opens.
 */
import { type PropsWithChildren, useEffect, useState } from 'react';
import { type GestureResponderEvent, Platform, Pressable, type StyleProp, StyleSheet, Text, useWindowDimensions, View, type ViewStyle } from 'react-native';
import Animated, {
  Easing,
  type SharedValue,
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withDelay,
  withSpring,
  withTiming,
} from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Svg, { Defs, LinearGradient, Rect, Stop } from 'react-native-svg';

import { Airfield, AIRFIELD_MS } from '@/components/login/airfield';
import { Swoosh } from '@/components/rw/icons';
import { T, useWide } from '@/components/rw/ui';
import { C, F } from '@/constants/runway';
import { httpStatus } from '@/hooks/use-load';
import { enterSignedIn, NotLinked, signIn } from '@/lib/account';
import { isAuthConfigured } from '@/lib/auth';
import { useSession } from '@/lib/session';

// the opening sequence, in ms from mount: the words arrive as the runway reaches the horizon
const OPEN = { brand: AIRFIELD_MS.horizon + 150, words: AIRFIELD_MS.runway + 250, button: AIRFIELD_MS.runway + 650 };
const TAKEOFF_MS = 1300;
// critically damped (no overshoot) — Apple's default for UI that wasn't flung
const SETTLE = { dampingRatio: 1, duration: 750 };
const FOLLOW = { dampingRatio: 1, duration: 900 };
const EASE_OUT = Easing.bezier(0.23, 1, 0.32, 1);

export function LoginScreen() {
  const wide = useWide();
  const reduced = useReducedMotion();
  const insets = useSafeAreaInsets();
  const { width, height } = useWindowDimensions();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const notice = useSession().notice; // why the last sign-in didn't finish (after coming back from Auth0)
  const shown = error ?? notice ?? null;

  const tilt = useSharedValue(0); // −1…1, where the pointer is across the screen
  const takeoff = useSharedValue(0); // 0…1, the plane's run to the horizon
  const lift = useSharedValue(0); // 0…1, the words leaving on sign-in

  function follow(e: { nativeEvent: { pageX?: number; clientX?: number } }) {
    if (reduced) return;
    const x = e.nativeEvent.clientX ?? e.nativeEvent.pageX ?? width / 2;
    tilt.set(withSpring(Math.max(-1, Math.min(1, (x / width) * 2 - 1)), FOLLOW));
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
      if (reduced) {
        enterSignedIn(profile);
        return;
      }
      tilt.set(withSpring(0, FOLLOW)); // line the runway up for the takeoff
      lift.set(withTiming(1, { duration: 420, easing: EASE_OUT }));
      takeoff.set(withDelay(150, withTiming(1, { duration: TAKEOFF_MS - 150, easing: Easing.in(Easing.cubic) })));
      setTimeout(() => enterSignedIn(profile), TAKEOFF_MS);
    } catch (e) {
      setBusy(false);
      const code = httpStatus(e instanceof Error ? e.message : '');
      setError(e instanceof NotLinked ? e.message : `Sign-in didn’t finish${code ? ` (error ${code})` : ''}. Please try again.`);
    }
  }

  const liftStyle = useAnimatedStyle(() => ({ opacity: 1 - lift.get(), transform: [{ translateY: -18 * lift.get() }] }));
  const fieldHeight = Math.round(Math.max(150, Math.min(height * 0.34, 340)));
  // the website follows the mouse; phones have no hover, so they keep the runway centred
  const pointer = Platform.OS === 'web' ? { onPointerMove: follow, onPointerLeave: () => tilt.set(withSpring(0, FOLLOW)) } : {};

  return (
    <View style={s.root} {...pointer}>
      <Backdrop />
      <Animated.View style={[s.column, { paddingTop: insets.top + 24, paddingHorizontal: wide ? 32 : 20 }, liftStyle]}>
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
              <SignInButton busy={busy} wide={wide} onPress={onSignIn} />
              <T tone="faint" style={s.note}>Auth0 handles your password. Runway never sees it.</T>
            </>
          ) : (
            <T tone="dim" style={s.note}>Sign-in isn’t switched on for this build. Set the Auth0 settings and rebuild.</T>
          )}
          {shown && (
            <T tone="red" style={s.note} accessibilityLiveRegion="polite">
              {shown}
            </T>
          )}
        </Settle>
      </Animated.View>
      <Airfield height={fieldHeight} tilt={tilt} takeoff={takeoff} />
    </View>
  );
}

/** Children that settle in once: a fade with a 14px rise on a critically damped spring. */
function Settle({ delay, children, style }: PropsWithChildren<{ delay: number; style?: StyleProp<ViewStyle> }>) {
  const reduced = useReducedMotion();
  const shown = useSharedValue(reduced ? 1 : 0);
  const rise = useSharedValue(reduced ? 0 : 14);
  useEffect(() => {
    if (reduced) {
      shown.set(1);
      rise.set(0);
      return;
    }
    shown.set(withDelay(delay, withTiming(1, { duration: 500, easing: EASE_OUT })));
    rise.set(withDelay(delay, withSpring(0, SETTLE)));
  }, [reduced, delay, shown, rise]);
  const anim = useAnimatedStyle(() => ({ opacity: shown.get(), transform: [{ translateY: rise.get() }] }));
  return <Animated.View style={[style, anim]}>{children}</Animated.View>;
}

/**
 * The one button. Lifts and glows under the pointer (website), presses in the moment it's touched,
 * springs back on release. Springs start from wherever the button is, so quick hover-in/out never jumps.
 */
function SignInButton({ busy, wide, onPress }: { busy: boolean; wide: boolean; onPress: () => void }) {
  const reduced = useReducedMotion();
  const hover = useSharedValue(0);
  const press = useSharedValue(0);
  const to = (v: SharedValue<number>, target: number, duration: number) => {
    if (!reduced) v.set(withSpring(target, { dampingRatio: 1, duration }));
  };
  const body = useAnimatedStyle(() => ({
    transform: [{ translateY: -2 * hover.get() }, { scale: 1 - 0.03 * press.get() }],
  }));
  const glow = useAnimatedStyle(() => ({ opacity: hover.get() * (1 - press.get() * 0.5) }));

  return (
    <Pressable
      accessibilityRole="button"
      disabled={busy}
      onPress={onPress}
      onHoverIn={() => to(hover, 1, 350)}
      onHoverOut={() => to(hover, 0, 350)}
      // feedback on press-down, not on release
      onPressIn={(_: GestureResponderEvent) => !reduced && press.set(withTiming(1, { duration: 90 }))}
      onPressOut={() => to(press, 0, 300)}
      style={[s.buttonSlot, !wide && s.buttonPhone]}>
      <Animated.View style={[s.glow, glow]} pointerEvents="none" />
      <Animated.View style={[s.button, busy && { opacity: 0.6 }, body]}>
        <Text style={s.buttonText}>{busy ? 'Opening Auth0…' : 'Continue with Auth0'}</Text>
      </Animated.View>
    </Pressable>
  );
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
  buttonSlot: { width: 320, height: 52 },
  buttonPhone: { width: '100%', maxWidth: 360 },
  button: { flex: 1, borderRadius: 26, backgroundColor: '#fff', alignItems: 'center', justifyContent: 'center' },
  // soft light under the lifted button
  glow: { position: 'absolute', top: 0, right: 0, bottom: 0, left: 0, borderRadius: 26, boxShadow: '0 10px 32px rgba(255,255,255,0.22)' },
  buttonText: { fontFamily: F.bodySemi, fontSize: 16, color: '#111', letterSpacing: 0.1 },
  note: { fontSize: 13, lineHeight: 19, textAlign: 'center' },
});

/**
 * Today with "Alerts only" on: one calm sentence instead of the balance, chart and tiles.
 *  - covered: "You're okay." and when the next paycheck lands — nothing to read, nothing to do
 *  - a dip coming: the day, what causes it, and one button that covers it (the same fix and
 *    approval sheet as the full screen; nothing moves until you say yes)
 *
 * Why it exists: in our buyer panel, 17 of the 20 people who said no gave the same reason — they
 * avoid looking at their balance, and a 30-day forecast is the screen they'd never open. What they
 * asked for was a heads-up only when something is about to go wrong, with a one-tap fix. The
 * numbers stay one tap away ("Show my numbers"), and the setting lives in the account menu.
 * "Get these on my phone" turns on the push alert itself (lib/push.ts), so they never have to open
 * the app to hear about a dip.
 */
import { useEffect, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import Animated, { FadeIn, useReducedMotion } from 'react-native-reanimated';
import Svg, { Circle, Path } from 'react-native-svg';

import { PressableScale } from '@/components/rw/ui';
import { describe, eventsOn, Fix } from '@/components/today/today-home';
import { alpha, C, F } from '@/constants/runway';
import { api } from '@/lib/api';
import { weekdayDate } from '@/lib/format';
import { enablePush, pushState, type PushState } from '@/lib/push';
import { isClear, nextPaycheck, runwayDays } from '@/lib/runway';
import { setStore, useStore } from '@/lib/store';
import type { Forecast, Me } from '@/lib/types';

export function QuietToday({ f, me }: { f: Forecast; me: Me | null }) {
  const store = useStore();
  const reduced = useReducedMotion();
  const clear = isClear(f);
  const pay = nextPaycheck(f);
  const payday = pay ? weekdayDate(pay.date) : null;

  let title: string, line: string;
  if (clear) {
    title = 'You’re okay.';
    line = payday ? `Nothing to do before payday on ${payday}.` : 'Nothing to do this month.';
  } else {
    const first = runwayDays(f);
    const date = f.points[first].date;
    const cause = describe(eventsOn(f, date));
    title = first === 0 ? 'Heads up: you’re short today.' : `Heads up: you’d run short on ${weekdayDate(date)}.`;
    line = cause
      ? `${cause} comes out${payday ? ` before your ${payday} paycheck` : ''}.`
      : `Everyday spending adds up${payday ? ` before your ${payday} paycheck` : ''}.`;
  }
  const tone = clear ? C.green : C.amber; // amber, not red: a heads-up, not an alarm

  return (
    <Animated.View entering={reduced ? undefined : FadeIn.duration(320)} style={s.wrap}>
      <View style={[s.glyph, { backgroundColor: alpha(tone, '1f') }]} accessibilityElementsHidden importantForAccessibility="no">
        <Svg width={34} height={34} viewBox="0 0 24 24" fill="none" stroke={tone} strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round">
          {clear ? <Path d="M5 12.5l4.5 4.5L19 7.5" /> : (
            <>
              <Path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15z" />
              <Circle cx={12} cy={21} r={0.6} fill={tone} />
            </>
          )}
        </Svg>
      </View>
      <Text style={s.title} accessibilityRole="header" accessibilityLiveRegion="polite">{title}</Text>
      <Text style={s.line}>{line}</Text>

      <View style={s.fix}>
        <Fix f={f} me={me} approved={store.approvedAmount} />
      </View>
      {clear && <Text style={s.promise}>We’ll only speak up if that changes.</Text>}
      <PhoneAlerts />

      <PressableScale onPress={() => setStore({ peek: true })} accessibilityRole="button" style={s.peek}>
        <Text style={s.peekText}>Show my numbers</Text>
      </PressableScale>
    </Animated.View>
  );
}

/** Turn on the heads-up on this phone, or say what's in the way. Hidden where push can't work. */
function PhoneAlerts() {
  const [state, setState] = useState<PushState | null>(null);
  const [busy, setBusy] = useState(false);
  const [tested, setTested] = useState<string | null>(null);
  useEffect(() => {
    pushState().then(setState).catch(() => setState('unsupported'));
  }, []);

  async function turnOn() {
    setBusy(true);
    try {
      setState(await enablePush());
    } catch {
      setState('off');
      setTested('Couldn’t turn alerts on. Please try again.');
    } finally {
      setBusy(false);
    }
  }
  async function test() {
    setTested(null);
    try {
      const r = await api.pushTest();
      setTested(r.sent ? 'Sent. Check your notifications.' : 'Nothing reached this phone. Try turning alerts on again.');
    } catch {
      setTested('Couldn’t send a test right now.');
    }
  }

  if (state === null || state === 'unsupported' || state === 'server-off') return null;
  return (
    <View style={s.phone}>
      {state === 'off' && (
        <PressableScale onPress={turnOn} disabled={busy} accessibilityRole="button" style={[s.phoneBtn, busy && { opacity: 0.6 }]}>
          <Text style={s.phoneBtnText}>{busy ? 'Turning on…' : 'Get these on my phone'}</Text>
        </PressableScale>
      )}
      {state === 'on' && (
        <View style={s.phoneOn}>
          <Text style={s.phoneOnText}>Alerts are on for this phone</Text>
          <PressableScale onPress={test} accessibilityRole="button"><Text style={s.link}>Send a test</Text></PressableScale>
        </View>
      )}
      {state === 'home-screen' && (
        <Text style={s.hint}>To get these as alerts on iPhone, tap Share, then Add to Home Screen, and open Runway from there.</Text>
      )}
      {state === 'denied' && <Text style={s.hint}>Notifications are blocked for Runway. Allow them in your browser settings to get alerts.</Text>}
      {tested && <Text style={s.hint} accessibilityLiveRegion="polite">{tested}</Text>}
    </View>
  );
}

/** While peeking with alerts-only on: one tap back to the calm view. */
export function BackToQuiet() {
  return (
    <PressableScale onPress={() => setStore({ peek: false })} accessibilityRole="button" style={s.back}>
      <Text style={s.peekText}>Back to alerts only</Text>
    </PressableScale>
  );
}

const s = StyleSheet.create({
  wrap: { alignItems: 'center', paddingTop: 72, paddingHorizontal: 8, maxWidth: 460, width: '100%', alignSelf: 'center' },
  glyph: { width: 76, height: 76, borderRadius: 38, alignItems: 'center', justifyContent: 'center' },
  title: { fontFamily: F.bodySemi, fontSize: 30, lineHeight: 36, letterSpacing: -0.4, color: C.text, textAlign: 'center', marginTop: 22 },
  line: { fontFamily: F.body, fontSize: 17, lineHeight: 24, color: C.text2, textAlign: 'center', marginTop: 10 },
  fix: { alignSelf: 'stretch', marginTop: 10 },
  promise: { fontFamily: F.body, fontSize: 14, color: C.text3, textAlign: 'center', marginTop: 4 },
  peek: { marginTop: 36, paddingVertical: 10, paddingHorizontal: 18, borderRadius: 999, borderWidth: 1, borderColor: C.line },
  peekText: { fontFamily: F.bodySemi, fontSize: 14, color: C.text2 },
  phone: { alignSelf: 'stretch', alignItems: 'center', marginTop: 22, gap: 8 },
  phoneBtn: { height: 46, paddingHorizontal: 22, borderRadius: 999, backgroundColor: C.card2, alignItems: 'center', justifyContent: 'center' },
  phoneBtnText: { fontFamily: F.bodySemi, fontSize: 15, color: C.text },
  phoneOn: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  phoneOnText: { fontFamily: F.body, fontSize: 14, color: C.green },
  link: { fontFamily: F.bodySemi, fontSize: 14, color: C.text2, textDecorationLine: 'underline' },
  hint: { fontFamily: F.body, fontSize: 13, lineHeight: 19, color: C.text3, textAlign: 'center', maxWidth: 340 },
  back: { alignSelf: 'center', marginTop: 14, paddingVertical: 8, paddingHorizontal: 16, borderRadius: 999, borderWidth: 1, borderColor: C.line },
});

/**
 * The runway: its length is the number of days until checking falls under the safety floor.
 *
 * Motion (ported from app/prototypes/runway.html):
 *  - open (tens/day → short, state indication): the runway grows to its length, 300ms ease-out;
 *    the red end marker fades in after it lands. Nothing moves afterwards.
 *  - takeoff (rare, after an approved fix → delight budget): the end marker fades, the runway
 *    stretches to the full month (500ms ease-in-out) and the plane rolls and climbs along the path,
 *    drawing the red swoosh behind it (1100ms ease-in-out, starts 380ms in).
 *  - reduced motion: everything jumps to its end state.
 * All of it runs on the UI thread: shared values → animatedProps / animated styles, no setState per frame.
 *
 * Geometry is one 330×92 coordinate system scaled to the measured width, so the SVG and the
 * plane overlay (an Animated.View, transform-only) always line up.
 */
import { useEffect, useState } from 'react';
import { type LayoutChangeEvent, StyleSheet, View } from 'react-native';
import Animated, {
  Easing,
  useAnimatedProps,
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withDelay,
  withTiming,
} from 'react-native-reanimated';
import Svg, { Line, Path, Rect, Text as SvgText } from 'react-native-svg';

import { C, F } from '@/constants/runway';

const W = 330, H = 92, X0 = 4, X1 = 326, Y = 56, RH = 20, MID = Y + RH / 2, LIFT = 240, START = 22;
const C1 = [LIFT + 44, MID], C2 = [X1 - 62, 24], END = [X1 - 6, 6];
const SWOOSH = `M${LIFT},${MID} C${C1[0]},${C1[1]} ${C2[0]},${C2[1]} ${END[0]},${END[1]}`;
// Material "flight" glyph (Apache-2.0), drawn pointing up in a 24×24 box.
const PLANE = 'M21 16v-2l-8-5V3.5c0-.83-.67-1.5-1.5-1.5S10 2.67 10 3.5V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z';
const EASE_OUT = Easing.bezier(0.23, 1, 0.32, 1);
const EASE_IN_OUT = Easing.bezier(0.77, 0, 0.175, 1);

/* The takeoff path (ground roll, then the climb) sampled at equal arc-length steps once, in JS, so a
   worklet can place the plane with two array lookups per frame. */
const N = 240;
const PATH_SAMPLES = (() => {
  const raw: [number, number][] = [];
  for (let i = 0; i <= 60; i++) raw.push([START + ((LIFT - START) * i) / 60, MID]);
  for (let i = 1; i <= 200; i++) {
    const t = i / 200, u = 1 - t;
    raw.push([
      u * u * u * LIFT + 3 * u * u * t * C1[0] + 3 * u * t * t * C2[0] + t * t * t * END[0],
      u * u * u * MID + 3 * u * u * t * C1[1] + 3 * u * t * t * C2[1] + t * t * t * END[1],
    ]);
  }
  const cum = [0];
  for (let i = 1; i < raw.length; i++) cum.push(cum[i - 1] + Math.hypot(raw[i][0] - raw[i - 1][0], raw[i][1] - raw[i - 1][1]));
  const total = cum[cum.length - 1];
  const xs: number[] = [], ys: number[] = [], angles: number[] = [];
  let j = 0;
  for (let k = 0; k < N; k++) {
    const target = (k / (N - 1)) * total;
    while (j < cum.length - 2 && cum[j + 1] < target) j++;
    const f = (target - cum[j]) / (cum[j + 1] - cum[j] || 1);
    xs.push(raw[j][0] + (raw[j + 1][0] - raw[j][0]) * f);
    ys.push(raw[j][1] + (raw[j + 1][1] - raw[j][1]) * f);
  }
  for (let k = 0; k < N; k++) {
    const a = Math.min(k, N - 2);
    angles.push((Math.atan2(ys[a + 1] - ys[a], xs[a + 1] - xs[a]) * 180) / Math.PI);
  }
  const groundLen = LIFT - START;
  return { xs, ys, angles, airStart: groundLen / total, swooshLen: total - groundLen };
})();

const AnimatedRect = Animated.createAnimatedComponent(Rect);
const AnimatedLine = Animated.createAnimatedComponent(Line);
const AnimatedPath = Animated.createAnimatedComponent(Path);
const AnimatedText = Animated.createAnimatedComponent(SvgText);

type Props = {
  /** days of runway (0…horizon) */
  days: number;
  horizon: number;
  /** "Oct 22" — the day it runs out (ignored when clear) */
  endLabel: string;
  /** "Nov 16" — the last day of the horizon */
  lastLabel: string;
  /** bump to play the takeoff (from the current runway to clear) */
  takeoffKey: number;
};

export function RunwayStrip({ days, horizon, endLabel, lastLabel, takeoffKey }: Props) {
  const reduced = useReducedMotion();
  const clear = days >= horizon;
  const endX = X0 + (Math.min(days, horizon) / horizon) * (X1 - X0);
  const [width, setWidth] = useState(0);

  const run = useSharedValue(0); // runway length, 0…1 of the strip
  const plane = useSharedValue(clear ? 1 : 0); // position along the takeoff path
  const endOpacity = useSharedValue(0);
  const ghostOpacity = useSharedValue(clear ? 0 : 1);
  const scale = useSharedValue(1); // px per geometry unit, for the overlay
  // Keeps the last real end label so it can fade out during the takeoff (when the new one is '').
  const [label, setLabel] = useState(endLabel);
  if (endLabel && endLabel !== label) setLabel(endLabel);

  // Open: grow to length. Runs on mount and when the runway changes without a takeoff (e.g. refresh).
  useEffect(() => {
    const target = (endX - X0) / (X1 - X0);
    if (takeoffKey > 0) return; // the takeoff effect owns the motion after an approval
    plane.set(clear ? 1 : 0);
    ghostOpacity.set(clear ? 0 : 1);
    if (reduced) {
      run.set(target);
      endOpacity.set(clear ? 0 : 1);
      return;
    }
    run.set(0);
    run.set(withDelay(80, withTiming(target, { duration: 300, easing: EASE_OUT })));
    endOpacity.set(0);
    endOpacity.set(clear ? 0 : withDelay(380, withTiming(1, { duration: 180, easing: EASE_OUT })));
  }, [endX, clear, endLabel, reduced, takeoffKey, run, plane, endOpacity, ghostOpacity]);

  // Takeoff: only once per bump, only when the new state is clear.
  useEffect(() => {
    if (takeoffKey === 0 || !clear) return;
    if (reduced) {
      run.set(1); plane.set(1); endOpacity.set(0); ghostOpacity.set(0);
      return;
    }
    plane.set(0);
    endOpacity.set(withTiming(0, { duration: 160, easing: EASE_OUT }));
    ghostOpacity.set(withTiming(0, { duration: 200, easing: EASE_OUT }));
    run.set(withTiming(1, { duration: 500, easing: EASE_IN_OUT }));
    plane.set(withDelay(380, withTiming(1, { duration: 1100, easing: EASE_IN_OUT })));
  }, [takeoffKey, clear, reduced, run, plane, endOpacity, ghostOpacity]);

  const onLayout = (e: LayoutChangeEvent) => {
    const w = e.nativeEvent.layout.width;
    setWidth(w);
    scale.set(w / W);
  };

  const runwayProps = useAnimatedProps(() => ({ width: (X1 - X0) * run.get() }));
  const dashProps = useAnimatedProps(() => ({ x2: X0 + 26 + Math.max(0, (X1 - X0) * run.get() - 30) }));
  const endProps = useAnimatedProps(() => ({ x: X0 + (X1 - X0) * run.get() - 4, opacity: endOpacity.get() }));
  const fadeProps = useAnimatedProps(() => ({ x: X0 + (X1 - X0) * run.get() - 22, opacity: endOpacity.get() }));
  const labelProps = useAnimatedProps(() => ({ opacity: endOpacity.get() }));
  const ghostProps = useAnimatedProps(() => ({ opacity: ghostOpacity.get() }));
  const swooshProps = useAnimatedProps(() => {
    const { airStart, swooshLen } = PATH_SAMPLES;
    const air = Math.max(0, (plane.get() - airStart) / (1 - airStart));
    return { strokeDashoffset: swooshLen * (1 - air) };
  });

  // Plane + shadow ride above the SVG as transform-only views.
  const planeStyle = useAnimatedStyle(() => {
    const { xs, ys, angles } = PATH_SAMPLES;
    const i = Math.min(N - 1, Math.round(plane.get() * (N - 1)));
    const alt = Math.max(0, MID - ys[i]);
    const grow = 1 + Math.min(alt / 56, 1) * 0.3;
    const s = scale.get();
    return {
      transform: [
        { translateX: xs[i] * s - 12 },
        { translateY: ys[i] * s - 12 },
        { rotate: `${angles[i] + 90}deg` }, // glyph points up; +90 aims it along the path
        { scale: 0.82 * grow * Math.max(s, 0.8) },
      ],
    };
  });
  const shadowStyle = useAnimatedStyle(() => {
    const { xs, ys } = PATH_SAMPLES;
    const i = Math.min(N - 1, Math.round(plane.get() * (N - 1)));
    const alt = Math.max(0, MID - ys[i]);
    const s = scale.get();
    return {
      opacity: 0.45 * Math.max(0, 1 - alt / 30),
      transform: [{ translateX: Math.min(xs[i], LIFT + 30) * s - 9 }, { translateY: (MID + 4) * s - 3 }],
    };
  });

  const keys = [0, 1, 2, 3].map((i) => <Rect key={i} x={X0 + 5} y={Y + 3 + i * 4.4} width={9} height={2.4} rx={1} fill="#fff" opacity={0.5} />);

  return (
    <View onLayout={onLayout} style={{ width: '100%', aspectRatio: W / H }}
      accessible accessibilityRole="image"
      accessibilityLabel={clear ? 'Runway clear for the next 30 days' : `${days} days until money runs low, on ${endLabel}`}>
      {width > 0 && (
        <>
          <Svg width={width} height={width * (H / W)} viewBox={`0 0 ${W} ${H}`}>
            {/* the rest of the month, where the runway would need to be */}
            <Line x1={X0} x2={X1} y1={MID} y2={MID} stroke="rgba(255,255,255,0.16)" strokeDasharray="2 5" strokeLinecap="round" />
            <AnimatedRect x={X0} y={Y} height={RH} rx={6} fill="#363e47" animatedProps={runwayProps} />
            {keys}
            <AnimatedLine x1={X0 + 26} y1={MID} y2={MID} stroke="rgba(255,255,255,0.35)" strokeWidth={2} strokeDasharray="10 9" animatedProps={dashProps} />
            <AnimatedRect y={Y} width={22} height={RH} fill={C.red} animatedProps={fadeProps} fillOpacity={0.18} />
            <AnimatedRect y={Y - 5} width={4} height={RH + 10} rx={2} fill={C.red} animatedProps={endProps} />
            <AnimatedPath d={SWOOSH} fill="none" stroke="rgba(255,255,255,0.2)" strokeWidth={2} strokeDasharray="3 6" strokeLinecap="round" animatedProps={ghostProps} />
            <AnimatedPath d={SWOOSH} fill="none" stroke={C.red} strokeWidth={3.5} strokeLinecap="round"
              strokeDasharray={`${PATH_SAMPLES.swooshLen} ${PATH_SAMPLES.swooshLen}`} animatedProps={swooshProps} />
            <SvgText x={X0} y={H - 2} fill={C.text3} fontSize={10} fontFamily={F.cond} letterSpacing={1}>TODAY</SvgText>
            {!clear || takeoffKey > 0 ? (
              <AnimatedText x={endX} y={Y - 9} fill={C.red} fontSize={10} fontFamily={F.condBold} letterSpacing={1} textAnchor="middle" animatedProps={labelProps}>
                {label.toUpperCase()}
              </AnimatedText>
            ) : null}
            <SvgText x={X1} y={H - 2} fill={C.text3} fontSize={10} fontFamily={F.cond} letterSpacing={1} textAnchor="end">{lastLabel.toUpperCase()}</SvgText>
          </Svg>
          <Animated.View pointerEvents="none" style={[s.shadow, { width: 18, height: 6 }, shadowStyle]} />
          <Animated.View pointerEvents="none" style={[s.plane, planeStyle]}>
            <Svg width={24} height={24} viewBox="0 0 24 24"><Path d={PLANE} fill="#fff" /></Svg>
          </Animated.View>
        </>
      )}
    </View>
  );
}

const s = StyleSheet.create({
  plane: { position: 'absolute', left: 0, top: 0, width: 24, height: 24 },
  shadow: { position: 'absolute', left: 0, top: 0, borderRadius: 9, backgroundColor: '#000' },
});

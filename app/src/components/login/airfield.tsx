/**
 * The login backdrop: a runway in perspective, drawn in hairlines, running from the bottom edge to
 * the horizon.
 *
 * Motion (all on the UI thread; reduced motion → drawn in place, nothing moves):
 *  - open, once: the horizon spreads from the centre, then the runway uncovers from your feet up to
 *    the vanishing point;
 *  - approach lights: the edge lights pulse in sequence toward the horizon every few seconds — the
 *    "rabbit" real airfields use to lead a pilot's eye in, here leading yours up to the sign-in;
 *  - parallax: the vanishing point follows the pointer a little (`tilt`, −1…1, springs owned by the
 *    screen), so the field has depth;
 *  - takeoff: on sign-in a plane rolls up the centre line and shrinks into the horizon (`takeoff`, 0…1).
 *
 * Geometry is plain perspective: a marking at distance z sits at y = depth / z below the horizon,
 * and every point slides linearly from its fixed spot on the bottom edge to the vanishing point,
 * so moving the vanishing point re-aims the whole field.
 */
import { useEffect, useState } from 'react';
import { type LayoutChangeEvent, StyleSheet, View } from 'react-native';
import Animated, {
  Easing,
  type SharedValue,
  useAnimatedProps,
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withDelay,
  withRepeat,
  withSequence,
  withTiming,
} from 'react-native-reanimated';
import Svg, { Circle, Line, Path } from 'react-native-svg';

import { PALETTES } from '@/constants/runway';


// the sign-in screen is a night airfield in every theme
const NIGHT = PALETTES.dark;

const EASE = Easing.bezier(0.77, 0, 0.175, 1);
const STROKE = 'rgba(255,255,255,0.22)';
const FAINT = 'rgba(255,255,255,0.12)';
const SWAY = 0.07; // how far the vanishing point travels with the pointer, as a share of the width
const LIGHT_CYCLE = 4200; // ms from the start of one run of approach lights to the next
const LIGHT_RUN = 1500; // ms for one run from the near end to the horizon

const BARS = [1.25, 1.7, 2.5, 4, 7];
const DASHES = (() => {
  const out: [number, number][] = [];
  for (let z = 1.05; z < 26; z *= 1.32) out.push([z, z * 1.14]);
  return out;
})();
const LIGHTS = [1.08, 1.35, 1.75, 2.4, 3.4, 5, 7.5, 11];
// Material "flight" glyph (Apache-2.0), pointing up in a 24×24 box — the same plane as the app's runway.
const PLANE = 'M21 16v-2l-8-5V3.5c0-.83-.67-1.5-1.5-1.5S10 2.67 10 3.5V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z';

export const AIRFIELD_MS = { horizon: 100, runway: 450, runwayFor: 1100 };

const AnimatedLine = Animated.createAnimatedComponent(Line);
const AnimatedCircle = Animated.createAnimatedComponent(Circle);

type Geo = { w: number; h: number; halfNear: number };

export function Airfield({ height, tilt, takeoff }: { height: number; tilt: SharedValue<number>; takeoff: SharedValue<number> }) {
  const reduced = useReducedMotion();
  const [w, setW] = useState(0);
  const horizon = useSharedValue(reduced ? 1 : 0);
  const reveal = useSharedValue(reduced ? 1 : 0);
  const lights = useSharedValue(-1); // where the pulse is, 0 (near end) … 1 (horizon); off the ends = dark

  useEffect(() => {
    if (reduced) {
      horizon.set(1);
      reveal.set(1);
      lights.set(-1);
      return;
    }
    horizon.set(withDelay(AIRFIELD_MS.horizon, withTiming(1, { duration: 800, easing: EASE })));
    reveal.set(withDelay(AIRFIELD_MS.runway, withTiming(1, { duration: AIRFIELD_MS.runwayFor, easing: EASE })));
    // the first run starts as the runway finishes drawing, then one every LIGHT_CYCLE ms
    lights.set(
      withDelay(
        AIRFIELD_MS.runway + AIRFIELD_MS.runwayFor - 200,
        withRepeat(
          withSequence(
            withTiming(-0.3, { duration: 0 }),
            withTiming(1.3, { duration: LIGHT_RUN, easing: Easing.inOut(Easing.quad) }),
            withTiming(1.3, { duration: LIGHT_CYCLE - LIGHT_RUN }),
          ),
          -1,
        ),
      ),
    );
  }, [reduced, horizon, reveal, lights]);

  const horizonStyle = useAnimatedStyle(() => ({ transform: [{ scaleX: horizon.get() }] }));
  // the runway is uncovered from the bottom edge up to the horizon
  const revealStyle = useAnimatedStyle(() => ({ height: height * reveal.get() }));

  const onLayout = (e: LayoutChangeEvent) => setW(e.nativeEvent.layout.width);
  const geo: Geo = { w, h: height, halfNear: Math.min(w * 0.42, height * 1.6) };

  return (
    <View onLayout={onLayout} pointerEvents="none" style={[s.field, { height }]}>
      <Animated.View style={[s.horizon, horizonStyle]} />
      {w > 0 && (
        <Animated.View style={[s.reveal, revealStyle]}>
          <Svg width={w} height={height} style={s.svg}>
            <Edge geo={geo} side={-1} tilt={tilt} />
            <Edge geo={geo} side={1} tilt={tilt} />
            {BARS.map((z) => <Bar key={z} geo={geo} z={z} tilt={tilt} />)}
            {DASHES.map(([z1, z2]) => <Dash key={z1} geo={geo} z1={z1} z2={z2} tilt={tilt} />)}
            {[-1, 1].flatMap((side) =>
              LIGHTS.map((z, i) => (
                <Light key={`${side}:${z}`} geo={geo} z={z} at={i / (LIGHTS.length - 1)} side={side} tilt={tilt} pulse={lights} />
              )),
            )}
          </Svg>
          <Plane geo={geo} tilt={tilt} takeoff={takeoff} />
        </Animated.View>
      )}
    </View>
  );
}

/* ---- geometry, shared by JS and worklets ---- */

/** x of a point that sits at `nearX` on the bottom edge, `y` px below the horizon. */
function xAt(nearX: number, y: number, h: number, vpx: number) {
  'worklet';
  return vpx + (nearX - vpx) * (y / h); // y / h: 0 at the horizon, 1 at the bottom edge
}

/** x of the vanishing point for a tilt of −1…1. */
function vp(geo: Geo, tilt: number) {
  'worklet';
  return geo.w / 2 + tilt * geo.w * SWAY;
}

function Edge({ geo, side, tilt }: { geo: Geo; side: number; tilt: SharedValue<number> }) {
  const props = useAnimatedProps(() => ({ x2: vp(geo, tilt.get()) + side * 3 }));
  return <AnimatedLine x1={geo.w / 2 + side * geo.halfNear} y1={geo.h} y2={0} stroke={STROKE} strokeWidth={1} animatedProps={props} />;
}

function Bar({ geo, z, tilt }: { geo: Geo; z: number; tilt: SharedValue<number> }) {
  const y = geo.h / z;
  const props = useAnimatedProps(() => {
    const v = vp(geo, tilt.get());
    return { x1: xAt(geo.w / 2 - geo.halfNear, y, geo.h, v), x2: xAt(geo.w / 2 + geo.halfNear, y, geo.h, v) };
  });
  return <AnimatedLine y1={y} y2={y} stroke={FAINT} strokeWidth={1} animatedProps={props} />;
}

function Dash({ geo, z1, z2, tilt }: { geo: Geo; z1: number; z2: number; tilt: SharedValue<number> }) {
  const y1 = geo.h / z1, y2 = geo.h / z2;
  const props = useAnimatedProps(() => {
    const v = vp(geo, tilt.get());
    return { x1: xAt(geo.w / 2, y1, geo.h, v), x2: xAt(geo.w / 2, y2, geo.h, v) };
  });
  return <AnimatedLine y1={y1} y2={y2} stroke={STROKE} strokeWidth={1} animatedProps={props} />;
}

/** An edge light: always faintly on, brightening as the pulse passes its spot (`at`, 0…1). */
function Light({ geo, z, at, side, tilt, pulse }: {
  geo: Geo; z: number; at: number; side: number; tilt: SharedValue<number>; pulse: SharedValue<number>;
}) {
  const y = geo.h / z;
  const r = Math.max(1, 2.6 / Math.sqrt(z)); // farther lights are smaller
  const props = useAnimatedProps(() => {
    const d = (pulse.get() - at) / 0.16;
    return {
      cx: xAt(geo.w / 2 + side * (geo.halfNear + 10), y, geo.h, vp(geo, tilt.get())),
      opacity: 0.18 + 0.82 * Math.exp(-d * d),
    };
  });
  return <AnimatedCircle cy={y} r={r} fill={NIGHT.amber} animatedProps={props} />;
}

/** The plane that rolls up the centre line on sign-in and shrinks into the horizon. */
function Plane({ geo, tilt, takeoff }: { geo: Geo; tilt: SharedValue<number>; takeoff: SharedValue<number> }) {
  const style = useAnimatedStyle(() => {
    const t = takeoff.get();
    const z = 1.02 + t * t * 30; // equal steps of time cover less and less screen near the horizon
    const y = geo.h / z;
    const x = xAt(geo.w / 2, y, geo.h, vp(geo, tilt.get()));
    return {
      opacity: t <= 0 ? 0 : t > 0.92 ? (1 - t) / 0.08 : 1,
      transform: [{ translateX: x - 12 }, { translateY: y - 12 }, { scale: 34 / z / 24 }],
    };
  });
  return (
    <Animated.View pointerEvents="none" style={[s.plane, style]}>
      <Svg width={24} height={24} viewBox="0 0 24 24"><Path d={PLANE} fill="#fff" /></Svg>
    </Animated.View>
  );
}

const s = StyleSheet.create({
  field: { width: '100%', overflow: 'hidden' },
  horizon: { position: 'absolute', left: 0, right: 0, top: 0, height: 1, backgroundColor: NIGHT.text3, opacity: 0.6 },
  // anchored to the bottom, so growing its height uncovers the runway from the near end
  reveal: { position: 'absolute', left: 0, right: 0, bottom: 0, overflow: 'hidden' },
  svg: { position: 'absolute', left: 0, bottom: 0 },
  // positioned from the field's top (the horizon); only visible once the runway is fully drawn
  plane: { position: 'absolute', left: 0, top: 0, width: 24, height: 24 },
});

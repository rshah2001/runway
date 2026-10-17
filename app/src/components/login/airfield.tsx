/**
 * The login backdrop: a runway in perspective, drawn in hairlines, running from the bottom edge to
 * the horizon. On open it draws itself once — the horizon spreads out from the centre, then the
 * runway reveals from your feet toward the vanishing point — and then it stays still.
 *
 * Geometry is plain perspective: a marking at distance z sits at y = horizon + depth / z, so the
 * threshold bars and centre-line dashes bunch up toward the horizon the way real ones do.
 * Reduced motion: drawn in place.
 */
import { useEffect, useState } from 'react';
import { type LayoutChangeEvent, StyleSheet, View } from 'react-native';
import Animated, { Easing, useAnimatedStyle, useReducedMotion, useSharedValue, withDelay, withTiming } from 'react-native-reanimated';
import Svg, { Line } from 'react-native-svg';

import { C } from '@/constants/runway';

const EASE = Easing.bezier(0.77, 0, 0.175, 1);
const STROKE = 'rgba(255,255,255,0.22)';
const FAINT = 'rgba(255,255,255,0.12)';

export const AIRFIELD_MS = { horizon: 100, runway: 450, runwayFor: 1100 };

export function Airfield({ height }: { height: number }) {
  const reduced = useReducedMotion();
  const [w, setW] = useState(0);
  const horizon = useSharedValue(reduced ? 1 : 0);
  const reveal = useSharedValue(reduced ? 1 : 0);

  useEffect(() => {
    if (reduced) {
      horizon.set(1);
      reveal.set(1);
      return;
    }
    horizon.set(withDelay(AIRFIELD_MS.horizon, withTiming(1, { duration: 800, easing: EASE })));
    reveal.set(withDelay(AIRFIELD_MS.runway, withTiming(1, { duration: AIRFIELD_MS.runwayFor, easing: EASE })));
  }, [reduced, horizon, reveal]);

  const horizonStyle = useAnimatedStyle(() => ({ transform: [{ scaleX: horizon.get() }] }));
  // the runway is uncovered from the bottom edge up to the horizon
  const revealStyle = useAnimatedStyle(() => ({ height: height * reveal.get() }));

  const onLayout = (e: LayoutChangeEvent) => setW(e.nativeEvent.layout.width);

  return (
    <View onLayout={onLayout} pointerEvents="none" style={[s.field, { height }]}>
      <Animated.View style={[s.horizon, horizonStyle]} />
      {w > 0 && (
        <Animated.View style={[s.reveal, revealStyle]}>
          <Svg width={w} height={height} style={s.svg}>
            <Markings w={w} h={height} />
          </Svg>
        </Animated.View>
      )}
    </View>
  );
}

/** Edges, threshold bars and centre-line dashes, in perspective toward (w/2, 0). */
function Markings({ w, h }: { w: number; h: number }) {
  const cx = w / 2;
  const halfNear = Math.min(w * 0.42, h * 1.6); // half-width of the runway at the bottom edge
  const halfFar = 3; // …and where it meets the horizon
  const yAt = (z: number) => h / z; // distance z (1 = the bottom edge) → px below the horizon
  const halfAt = (y: number) => halfFar + (halfNear - halfFar) * (y / h);

  const bars = [1.25, 1.7, 2.5, 4, 7].map((z) => {
    const y = yAt(z), half = halfAt(y);
    return <Line key={`b${z}`} x1={cx - half} x2={cx + half} y1={y} y2={y} stroke={FAINT} strokeWidth={1} />;
  });

  const dashes = [];
  for (let z = 1.05; z < 26; z *= 1.32) {
    const y1 = yAt(z), y2 = yAt(z * 1.14);
    dashes.push(<Line key={`d${z}`} x1={cx} x2={cx} y1={y1} y2={y2} stroke={STROKE} strokeWidth={1} />);
  }

  return (
    <>
      <Line x1={cx - halfNear} y1={h} x2={cx - halfFar} y2={0} stroke={STROKE} strokeWidth={1} />
      <Line x1={cx + halfNear} y1={h} x2={cx + halfFar} y2={0} stroke={STROKE} strokeWidth={1} />
      {bars}
      {dashes}
    </>
  );
}

const s = StyleSheet.create({
  field: { width: '100%', overflow: 'hidden' },
  horizon: { position: 'absolute', left: 0, right: 0, top: 0, height: 1, backgroundColor: C.text3, opacity: 0.6 },
  // anchored to the bottom, so growing its height uncovers the runway from the near end
  reveal: { position: 'absolute', left: 0, right: 0, bottom: 0, overflow: 'hidden' },
  svg: { position: 'absolute', left: 0, bottom: 0 },
});

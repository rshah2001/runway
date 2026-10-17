/**
 * Hairlines that draw themselves in, once, when the login screen opens — the airfield's painted
 * markings going down before anything takes off. 1px strokes only; nothing moves after it lands.
 *
 * All of it runs on the UI thread (shared values → animated props/styles). With reduced motion
 * every piece starts in its final state.
 */
import { type PropsWithChildren, useEffect, useState } from 'react';
import { type LayoutChangeEvent, type StyleProp, StyleSheet, View, type ViewStyle } from 'react-native';
import Animated, {
  Easing,
  useAnimatedProps,
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withDelay,
  withTiming,
} from 'react-native-reanimated';
import Svg, { Rect } from 'react-native-svg';

import { C, RADIUS } from '@/constants/runway';

const EASE_OUT = Easing.bezier(0.23, 1, 0.32, 1);
const EASE_IN_OUT = Easing.bezier(0.77, 0, 0.175, 1);
const AnimatedRect = Animated.createAnimatedComponent(Rect);

/** 0 → 1 after `delay` ms over `duration` ms; already 1 with reduced motion. */
function useDraw(delay: number, duration: number, easing = EASE_OUT) {
  const reduced = useReducedMotion();
  const p = useSharedValue(reduced ? 1 : 0);
  useEffect(() => {
    if (reduced) {
      p.set(1);
      return;
    }
    p.set(withDelay(delay, withTiming(1, { duration, easing })));
  }, [reduced, delay, duration, easing, p]);
  return p;
}

/** A horizontal 1px line that draws from left to right. */
export function HairlineRule({ delay = 0, duration = 700, style }: { delay?: number; duration?: number; style?: StyleProp<ViewStyle> }) {
  const p = useDraw(delay, duration, EASE_IN_OUT);
  const line = useAnimatedStyle(() => ({ transform: [{ scaleX: p.get() }] }));
  return (
    <View style={[s.ruleTrack, style]} pointerEvents="none">
      <Animated.View style={[s.rule, line]} />
    </View>
  );
}

/** Children that settle in: a short fade and a 6px rise. */
export function Settle({ delay = 0, children, style }: PropsWithChildren<{ delay?: number; style?: StyleProp<ViewStyle> }>) {
  const p = useDraw(delay, 420);
  const anim = useAnimatedStyle(() => ({ opacity: p.get(), transform: [{ translateY: (1 - p.get()) * 6 }] }));
  return <Animated.View style={[anim, style]}>{children}</Animated.View>;
}

/**
 * A card whose 1px border traces itself clockwise from the top-left corner; the fill and the
 * contents fade in behind it, so the outline reads first.
 */
export function HairlineFrame({ delay = 0, duration = 900, children, style, contentStyle }: PropsWithChildren<{
  delay?: number;
  duration?: number;
  /** the frame: size and padding */
  style?: StyleProp<ViewStyle>;
  /** the contents' layout (e.g. gap), since they sit in their own fading wrapper */
  contentStyle?: StyleProp<ViewStyle>;
}>) {
  const [size, setSize] = useState({ w: 0, h: 0 });
  const trace = useDraw(delay, duration, EASE_IN_OUT);
  const fill = useDraw(delay + duration * 0.45, 500);

  const r = RADIUS;
  // perimeter of the rounded rectangle the stroke follows (inset half a pixel so it isn't clipped)
  const w = Math.max(0, size.w - 1), h = Math.max(0, size.h - 1);
  const perimeter = Math.max(0, 2 * (w + h) - 8 * r + 2 * Math.PI * r);

  const strokeProps = useAnimatedProps(() => ({ strokeDashoffset: perimeter * (1 - trace.get()) }));
  const fillStyle = useAnimatedStyle(() => ({ opacity: fill.get() }));

  const onLayout = (e: LayoutChangeEvent) => {
    const { width, height } = e.nativeEvent.layout;
    if (width !== size.w || height !== size.h) setSize({ w: width, h: height });
  };

  return (
    <View onLayout={onLayout} style={[s.frame, style]}>
      <Animated.View pointerEvents="none" style={[StyleSheet.absoluteFill, s.fill, fillStyle]} />
      {w > 2 * r && h > 2 * r && ( // only once measured: a stroke before then would flash in whole
        <Svg pointerEvents="none" style={StyleSheet.absoluteFill} width={size.w} height={size.h}>
          <AnimatedRect
            x={0.5} y={0.5} width={w} height={h} rx={r} ry={r}
            fill="none" stroke={C.text3} strokeOpacity={0.7} strokeWidth={1}
            strokeDasharray={`${perimeter} ${perimeter}`}
            animatedProps={strokeProps}
          />
        </Svg>
      )}
      <Animated.View style={[contentStyle, fillStyle]}>{children}</Animated.View>
    </View>
  );
}

const s = StyleSheet.create({
  ruleTrack: { height: 1, overflow: 'hidden' },
  // drawn from the left edge: the line is anchored there and scales out
  rule: { flex: 1, backgroundColor: C.text3, opacity: 0.7, transformOrigin: 'left' },
  frame: { borderRadius: RADIUS },
  fill: { backgroundColor: C.card, borderRadius: RADIUS },
});

/**
 * A small menu's arrival: it grows from its button (scale 0.92 → 1) with a quick fade (Apple: anchor
 * to the source), and fades out when closed. Hand-made rather than a reanimated `entering` Keyframe:
 * on the scaled-up desktop site a Keyframe writes the menu's size in screen pixels, so any re-render
 * while it's open (switching the theme, say) left the menu wider and shifted.
 */
import { type ReactNode, useEffect } from 'react';
import type { StyleProp, ViewStyle } from 'react-native';
import Animated, { Easing, FadeOut, useAnimatedStyle, useReducedMotion, useSharedValue, withTiming } from 'react-native-reanimated';

export function MenuGrow({ style, children }: { style: StyleProp<ViewStyle>; children: ReactNode }) {
  const reduced = useReducedMotion();
  const t = useSharedValue(reduced ? 1 : 0);
  useEffect(() => {
    if (!reduced) t.set(withTiming(1, { duration: 220, easing: Easing.bezier(0.23, 1, 0.32, 1) }));
  }, [t, reduced]);
  const grow = useAnimatedStyle(() => ({ opacity: t.get(), transform: [{ scale: 0.92 + 0.08 * t.get() }] }));
  return (
    <Animated.View exiting={FadeOut.duration(120)} style={[style, grow]} accessibilityRole="menu">
      {children}
    </Animated.View>
  );
}

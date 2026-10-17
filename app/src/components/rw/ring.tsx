/**
 * A WHOOP-style ring gauge. The arc sweeps to its value when it first appears and whenever the
 * value changes (700ms, ease-in-out — an on-screen change of state). Reduced motion: it jumps.
 */
import { useEffect } from 'react';
import { StyleSheet, View } from 'react-native';
import Animated, { Easing, useAnimatedProps, useReducedMotion, useSharedValue, withTiming } from 'react-native-reanimated';
import Svg, { Circle } from 'react-native-svg';

import { C } from '@/constants/runway';

import { Caps, Num } from './ui';

const AnimatedCircle = Animated.createAnimatedComponent(Circle);
const R = 44;
const CIRC = 2 * Math.PI * R;
const EASE_IN_OUT = Easing.bezier(0.77, 0, 0.175, 1);

type Props = {
  /** 0…1 of the ring filled */
  frac: number;
  color: string;
  value: string;
  unit: string;
  label: string;
  size?: number;
};

export function Ring({ frac, color, value, unit, label, size = 104 }: Props) {
  const reduced = useReducedMotion();
  const offset = useSharedValue(CIRC); // starts empty, sweeps in
  const clamped = Math.max(0, Math.min(1, frac));

  useEffect(() => {
    const to = CIRC * (1 - clamped);
    offset.set(reduced ? to : withTiming(to, { duration: 700, easing: EASE_IN_OUT }));
  }, [clamped, reduced, offset]);

  const arcProps = useAnimatedProps(() => ({ strokeDashoffset: offset.get() }));
  const long = value.length > 4;

  return (
    <View style={s.wrap} accessible accessibilityLabel={`${label}: ${value} ${unit}`}>
      <View style={{ width: size, height: size }}>
        <Svg width={size} height={size} viewBox="0 0 104 104" style={{ transform: [{ rotate: '-90deg' }] }}>
          <Circle cx={52} cy={52} r={R} fill="none" stroke={C.line} strokeWidth={8} />
          <AnimatedCircle cx={52} cy={52} r={R} fill="none" stroke={color} strokeWidth={8} strokeLinecap="round"
            strokeDasharray={`${CIRC} ${CIRC}`} animatedProps={arcProps} />
        </Svg>
        <View style={[StyleSheet.absoluteFill, s.center]}>
          <Num size={long ? (size * 0.26) : (size * 0.33)}>{value}</Num>
          <Caps tone="dim" size={11} style={{ marginTop: 2 }}>{unit}</Caps>
        </View>
      </View>
      <Caps size={14} style={{ marginTop: 8 }}>{label} <Caps tone="dim" size={16}>›</Caps></Caps>
    </View>
  );
}

const s = StyleSheet.create({
  wrap: { flex: 1, alignItems: 'center' },
  center: { alignItems: 'center', justifyContent: 'center' },
});

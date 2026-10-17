/**
 * The signed-in person's support circle, drawn: you in the middle, the people in your agreements
 * around you, one line per separately agreed relationship. Only YOUR relationships are ever drawn —
 * the API returns nothing else — so the map can't reveal who else someone supports, or anyone's money.
 *
 * Lines: solid = both agreed (active) · dashed = waiting for a yes · faded = stopped or paused.
 * Green = this person can cover you · blue = you can cover them. An amount on a line is money that is
 * out right now. Tap a person to select them (the screen shows their details and actions below).
 *
 * Motion (apple-design): people grow into place on mount on the iOS sheet curve (no overshoot,
 * ≈0.45 s), staggered a little so the ring reads as forming around you; press feedback is
 * instant; the selected person grows slightly. Reduced motion: they simply appear.
 */
import { useEffect, useState } from 'react';
import { type LayoutChangeEvent, StyleSheet, Text, View } from 'react-native';
import Animated, { Easing, useAnimatedStyle, useReducedMotion, useSharedValue, withDelay, withTiming } from 'react-native-reanimated';
import Svg, { Line, Text as SvgText } from 'react-native-svg';

import { PressableScale } from '@/components/rw/ui';
import { C, F } from '@/constants/runway';
import { money } from '@/lib/format';

export type CirclePerson = {
  key: string;
  name: string;
  /** supporter = can cover me · supported = I can cover them */
  role: 'supporter' | 'supported';
  /** active: both agreed · waiting: someone hasn't said yes · off: stopped/paused */
  status: 'active' | 'waiting' | 'off';
  /** money out right now on this relationship, if any */
  out?: number;
};

// muted, dark-friendly tints: people are told apart without the map turning into confetti
const TINTS = ['#2d6f86', '#6b6aa8', '#8f6aa8', '#8a6b45', '#2f7a68', '#7a4f5f', '#4f6f9a'];
// the iOS sheet curve: fast out, soft landing, no overshoot (springs with duration+dampingRatio don't
// settle on react-native-web, so a timed curve stands in)
const SETTLE = { duration: 450, easing: Easing.bezier(0.32, 0.72, 0, 1) } as const;
const NODE = 30; // radius of a person
const CENTER = 50;


export function CircleMap({ me, status, tone, people, selected, onSelect }: {
  me: string;
  status: string;
  tone: string;
  people: CirclePerson[];
  selected: string | null;
  onSelect: (key: string | null) => void;
}) {
  const [width, setWidth] = useState(0);
  const size = Math.min(width, 460);
  const height = Math.max(300, size * 0.86);
  const cx = width / 2;
  const cy = height / 2;
  const ring = Math.min(size / 2 - NODE - 14, height / 2 - NODE - 10);
  const spots = people.map((p, i) => {
    const a = -Math.PI / 2 + (i * 2 * Math.PI) / Math.max(people.length, 1);
    return { p, x: cx + ring * Math.cos(a), y: cy + ring * Math.sin(a) };
  });

  return (
    <View onLayout={(e: LayoutChangeEvent) => setWidth(e.nativeEvent.layout.width)} style={[s.wrap, { height }]}>
      {width > 0 && (
        <>
          <Svg width={width} height={height} style={StyleSheet.absoluteFill}>
            {spots.map(({ p, x, y }) => {
              const color = p.status === 'off' ? C.text3 : p.role === 'supporter' ? C.green : '#7cb8ff';
              const mx = (cx + x) / 2;
              const my = (cy + y) / 2;
              return [
                <Line key={`l-${p.key}`} x1={cx} y1={cy} x2={x} y2={y} stroke={color}
                  strokeOpacity={p.status === 'off' ? 0.35 : selected && selected !== p.key ? 0.35 : 0.85}
                  strokeWidth={p.status === 'active' ? 2 : 1.5} strokeDasharray={p.status === 'active' ? undefined : '5 6'} />,
                p.out ? (
                  <SvgText key={`t-${p.key}`} x={mx + (x >= cx ? 10 : -10)} y={my + 4} fill={color} fontSize={13} fontWeight="700"
                    textAnchor={x >= cx ? 'start' : 'end'}>
                    {money(p.out, 0)}
                  </SvgText>
                ) : null,
              ];
            })}
          </Svg>
          <Centre x={cx} y={cy} name={me} status={status} tone={tone} onPress={() => onSelect(null)} />
          {spots.map(({ p, x, y }, i) => (
            <Node key={p.key} p={p} x={x} y={y} index={i} on={selected === p.key}
              dim={!!selected && selected !== p.key} onPress={() => onSelect(selected === p.key ? null : p.key)} />
          ))}
        </>
      )}
    </View>
  );
}

function Centre({ x, y, name, status, tone, onPress }: { x: number; y: number; name: string; status: string; tone: string; onPress: () => void }) {
  return (
    <View style={[s.abs, { left: x - CENTER, top: y - CENTER }]}>
      <PressableScale onPress={onPress} accessibilityRole="button" accessibilityLabel={`${name}, ${status}`}
        style={[s.centre, { borderColor: tone }]}>
        <Text style={s.centreName} numberOfLines={1}>{name}</Text>
        <Text style={[s.centreStatus, { color: tone }]} numberOfLines={1}>{status}</Text>
      </PressableScale>
    </View>
  );
}

function Node({ p, x, y, index, on, dim, onPress }: {
  p: CirclePerson; x: number; y: number; index: number; on: boolean; dim: boolean; onPress: () => void;
}) {
  const reduced = useReducedMotion();
  const t = useSharedValue(reduced ? 1 : 0); // 0 hidden … 1 in place
  const grow = useSharedValue(1);
  useEffect(() => {
    t.set(reduced ? 1 : withDelay(70 * index, withTiming(1, SETTLE)));
  }, [t, reduced, index]);
  useEffect(() => {
    grow.set(reduced ? 1 : withTiming(on ? 1.12 : 1, { duration: 250, easing: SETTLE.easing }));
  }, [grow, on, reduced]);
  // only scale + opacity animate (no position): positions come from layout, so a resize can't strand them
  // visible from the first frame: the motion only adds a slight grow-in, so a throttled tab (or
  // stalled animation frames) can never leave someone missing from the map
  const style = useAnimatedStyle(() => ({ transform: [{ scale: (0.82 + 0.18 * t.get()) * grow.get() }] }));
  const role = p.role === 'supporter' ? 'can cover you' : 'you can cover them';
  return (
    <View style={[s.abs, { left: x - NODE, top: y - NODE, opacity: dim ? 0.55 : 1 }]}>
      <Animated.View style={style}>
        <PressableScale onPress={onPress} accessibilityRole="button" accessibilityState={{ selected: on }}
          accessibilityLabel={`${p.name}, ${role}, ${p.status === 'active' ? 'agreed' : p.status === 'waiting' ? 'waiting for a yes' : 'stopped'}`}
          style={[s.node, { backgroundColor: TINTS[index % TINTS.length] }, on && s.nodeOn, p.status === 'off' && { opacity: 0.6 }]}>
          <Text style={s.nodeName} numberOfLines={1}>{p.name}</Text>
        </PressableScale>
      </Animated.View>
    </View>
  );
}

export function CircleLegend() {
  return (
    <View style={s.legend}>
      <Key color={C.green} label="Can cover you" />
      <Key color="#7cb8ff" label="You can cover them" />
      <Key color={C.text2} dashed label="Waiting for a yes" />
    </View>
  );
}

function Key({ color, label, dashed }: { color: string; label: string; dashed?: boolean }) {
  return (
    <View style={s.key}>
      <View style={[s.swatch, { borderColor: color, borderStyle: dashed ? 'dashed' : 'solid' }]} />
      <Text style={s.keyText}>{label}</Text>
    </View>
  );
}

const s = StyleSheet.create({
  wrap: { width: '100%', marginTop: 4 },
  abs: { position: 'absolute' },
  centre: {
    width: CENTER * 2, height: CENTER * 2, borderRadius: CENTER, borderWidth: 3, backgroundColor: C.card2,
    alignItems: 'center', justifyContent: 'center', paddingHorizontal: 6,
  },
  centreName: { fontFamily: F.bodySemi, fontSize: 20, letterSpacing: -0.3, color: C.text },
  centreStatus: { fontFamily: F.bodySemi, fontSize: 13, marginTop: 2 },
  node: { width: NODE * 2, height: NODE * 2, borderRadius: NODE, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 4 },
  nodeOn: { borderWidth: 2, borderColor: '#fff' },
  nodeName: { fontFamily: F.bodySemi, fontSize: 13, color: '#fff' },
  legend: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'center', gap: 14, marginTop: 6 },
  key: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  swatch: { width: 18, height: 0, borderTopWidth: 2 },
  keyText: { fontFamily: F.body, fontSize: 12, color: C.text2 },
});

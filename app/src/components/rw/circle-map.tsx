/**
 * The signed-in person's support circle, drawn: you in the middle, the people in your agreements
 * around you, one line per separately agreed relationship. Only YOUR relationships are ever drawn —
 * the API returns nothing else — so the map can't reveal who else someone supports, or anyone's money.
 *
 * Lines: solid = both agreed (active) · dashed = waiting for a yes · faded = stopped or paused.
 * Green = this person can cover you · blue = you can cover them · dotted grey = in the same named circle
 * with no support agreement (a circle alone never means money). An amount on a line is money that is
 * out right now. Tap a person to select them (the screen shows their details and actions below).
 *
 * Motion (apple-design): people grow into place on mount on the iOS sheet curve (no overshoot,
 * ≈0.45 s), staggered a little so the ring reads as forming around you; press feedback is
 * instant; the selected person grows slightly. Reduced motion: they simply appear.
 */
import { useEffect, useState } from 'react';
import { type LayoutChangeEvent, StyleSheet, Text, View } from 'react-native';
import Animated, { Easing, useAnimatedStyle, useReducedMotion, useSharedValue, withDelay, withTiming } from 'react-native-reanimated';
import Svg, { Line } from 'react-native-svg';

import { PressableScale } from '@/components/rw/ui';
import { C, F } from '@/constants/runway';
import { money } from '@/lib/format';

export type CirclePerson = {
  key: string;
  name: string;
  /** supporter = can cover me · supported = I can cover them · member = shares a circle, no agreement */
  role: 'supporter' | 'supported' | 'member';
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
const LABEL = 24; // the name under a person
const PAD = 18; // breathing room above and below the group
const MIN_RING = CENTER + NODE + LABEL + 26; // room between you and a person for a name and an amount
const NAME_W = 110;
const AMOUNT_W = 64;

/** Green: this person can cover you · blue: you can cover them · grey: stopped. */
const lineColor = (p: CirclePerson) =>
  p.role === 'member' ? '#56616b' : p.status === 'off' ? C.text3 : p.role === 'supporter' ? C.green : '#7cb8ff';


export function CircleMap({ me, status, tone, people, selected, onSelect }: {
  me: string;
  status: string;
  tone: string;
  people: CirclePerson[];
  selected: string | null;
  onSelect: (key: string | null) => void;
}) {
  const [width, setWidth] = useState(0);
  // People sit evenly around you, as far out as the card's width allows (never so close that a name
  // or an amount runs into you). Then the whole group, not you, is centred in the card: with three
  // people (top, lower left, lower right) centring on you would leave the group high and a gap below.
  const angles = people.map((_, i) => -Math.PI / 2 + (i * 2 * Math.PI) / Math.max(people.length, 1));
  const widest = Math.max(0.5, ...angles.map((a) => Math.abs(Math.cos(a))));
  const ring = Math.max(MIN_RING, Math.min(150, (width / 2 - NODE - 10) / widest));
  const raw = people.map((p, i) => ({ p, dx: ring * Math.cos(angles[i]), dy: ring * Math.sin(angles[i]) }));
  // a person above you has their name above them, so the line to you never runs through it
  const top = Math.min(-CENTER, ...raw.map((r) => r.dy - NODE - (r.dy < -1 ? LABEL : 0)));
  const bottom = Math.max(CENTER, ...raw.map((r) => r.dy + NODE + (r.dy < -1 ? 0 : LABEL)));
  const height = bottom - top + PAD * 2;
  const cx = width / 2;
  const cy = PAD - top;
  const spots = raw.map(({ p, dx, dy }) => ({ p, x: cx + dx, y: cy + dy }));

  return (
    <View onLayout={(e: LayoutChangeEvent) => setWidth(e.nativeEvent.layout.width)} style={[s.wrap, { height }]}>
      {width > 0 && (
        <>
          <Svg width={width} height={height} style={StyleSheet.absoluteFill}>
            {spots.map(({ p, x, y }) => {
              const color = lineColor(p);
              // each line runs from the edge of your circle to the edge of theirs, never underneath either
              const len = Math.hypot(x - cx, y - cy) || 1, ux = (x - cx) / len, uy = (y - cy) / len;
              return (
                <Line key={`l-${p.key}`} x1={cx + ux * CENTER} y1={cy + uy * CENTER} x2={x - ux * NODE} y2={y - uy * NODE} stroke={color}
                  strokeOpacity={p.status === 'off' ? 0.35 : selected && selected !== p.key ? 0.35 : 0.85}
                  strokeWidth={p.status === 'active' ? 2 : 1.5}
                  strokeDasharray={p.role === 'member' ? '1 6' : p.status === 'active' ? undefined : '5 6'} strokeLinecap="round" />
              );
            })}
          </Svg>
          {/* money out right now: a small pill sitting on the middle of its line */}
          {spots.map(({ p, x, y }) => p.out ? (
            <View key={`t-${p.key}`} pointerEvents="none"
              style={[s.abs, s.amount, { left: (cx + x) / 2 - AMOUNT_W / 2, top: (cy + y) / 2 - 11, borderColor: lineColor(p) }]}>
              <Text style={[s.amountText, { color: lineColor(p) }]}>{money(p.out, 0)}</Text>
            </View>
          ) : null)}
          <Centre x={cx} y={cy} name={me} status={status} tone={tone} onPress={() => onSelect(null)} />
          {spots.map(({ p, x, y }, i) => (
            <Node key={p.key} p={p} x={x} y={y} above={y < cy - 1} index={i} on={selected === p.key}
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

function Node({ p, x, y, above, index, on, dim, onPress }: {
  p: CirclePerson; x: number; y: number; above: boolean; index: number; on: boolean; dim: boolean; onPress: () => void;
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
  const role = p.role === 'supporter' ? 'can cover you' : p.role === 'supported' ? 'you can cover them' : 'in this circle';
  return (
    <View style={[s.abs, { left: x - NAME_W / 2, top: y - NODE - (above ? LABEL : 0), width: NAME_W, alignItems: 'center', opacity: dim ? 0.55 : 1 }]}>
      {above && <Text style={[s.nodeName, s.nameAbove, on && { color: C.text }]} numberOfLines={1}>{p.name}</Text>}
      <Animated.View style={style}>
        <PressableScale onPress={onPress} accessibilityRole="button" accessibilityState={{ selected: on }}
          accessibilityLabel={p.role === 'member' ? `${p.name}, ${role}` : `${p.name}, ${role}, ${p.status === 'active' ? 'agreed' : p.status === 'waiting' ? 'waiting for a yes' : 'stopped'}`}
          style={[s.node, { borderColor: lineColor(p), borderStyle: p.role === 'member' ? 'dotted' : p.status === 'waiting' ? 'dashed' : 'solid' }, on && s.nodeOn,
            p.status === 'off' && { opacity: 0.6 }]}>
          {/* a solid disc first, so no line ever shows through; the person's tint sits on top of it */}
          <View style={[StyleSheet.absoluteFill, s.tint, { backgroundColor: `${TINTS[index % TINTS.length]}55` }]} />
          <Text style={s.nodeInitial}>{p.name[0]}</Text>
        </PressableScale>
        {!above && <Text style={[s.nodeName, on && { color: C.text }]} numberOfLines={1}>{p.name}</Text>}
      </Animated.View>
    </View>
  );
}

export function CircleLegend({ members = false }: { members?: boolean }) {
  return (
    <View style={s.legend}>
      <Key color={C.green} label="Can cover you" />
      <Key color="#7cb8ff" label="You can cover them" />
      <Key color={C.text2} dashed label="Waiting for a yes" />
      {members && <Key color="#56616b" dotted label="In this circle" />}
    </View>
  );
}

function Key({ color, label, dashed, dotted }: { color: string; label: string; dashed?: boolean; dotted?: boolean }) {
  return (
    <View style={s.key}>
      <View style={[s.swatch, { borderColor: color, borderStyle: dotted ? 'dotted' : dashed ? 'dashed' : 'solid' }]} />
      <Text style={s.keyText}>{label}</Text>
    </View>
  );
}

const s = StyleSheet.create({
  wrap: { width: '100%', marginTop: 4 }, // height is set from the group's own size
  abs: { position: 'absolute' },
  centre: {
    width: CENTER * 2, height: CENTER * 2, borderRadius: CENTER, borderWidth: 3, backgroundColor: C.card2,
    alignItems: 'center', justifyContent: 'center', paddingHorizontal: 6,
  },
  centreName: { fontFamily: F.bodySemi, fontSize: 20, letterSpacing: -0.3, color: C.text },
  centreStatus: { fontFamily: F.bodySemi, fontSize: 13, marginTop: 2 },
  node: { width: NODE * 2, height: NODE * 2, borderRadius: NODE, borderWidth: 2.5, alignItems: 'center', justifyContent: 'center',
    backgroundColor: C.card2, overflow: 'hidden' },
  tint: { borderRadius: NODE },
  nameAbove: { marginTop: 0, marginBottom: 5 },
  nodeOn: { borderWidth: 3.5 },
  nodeInitial: { fontFamily: F.bodySemi, fontSize: 22, color: C.text },
  nodeName: { fontFamily: F.bodySemi, fontSize: 13, color: C.text2, marginTop: 5, textAlign: 'center' },
  amount: { width: AMOUNT_W, height: 22, borderRadius: 11, borderWidth: 1, backgroundColor: C.card, alignItems: 'center', justifyContent: 'center' },
  amountText: { fontFamily: F.condBold, fontSize: 13, letterSpacing: 0.3 },
  legend: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'center', gap: 14, marginTop: 6 },
  key: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  swatch: { width: 18, height: 0, borderTopWidth: 2 },
  keyText: { fontFamily: F.body, fontSize: 12, color: C.text2 },
});

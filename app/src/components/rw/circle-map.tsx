/**
 * Your support circle, in the iOS Contacts / Family Sharing idiom: you in the middle inside a thin
 * status ring, the people in your agreements around you as soft monogram avatars, hairline connectors
 * between you. A small badge on each avatar says where things stand (check = you've both agreed,
 * dots = waiting for a yes); colour appears only where it means something. Money that is out right now
 * sits on its connector in a small capsule.
 *
 * Only YOUR relationships are drawn — the API returns nothing else — so it can't reveal who else
 * someone supports, or anyone's money. Tap a person to select them; the screen shows details below.
 */
import { useState } from 'react';
import { type LayoutChangeEvent, Pressable, StyleSheet, Text, View } from 'react-native';
import Svg, { Circle, Defs, G, Line, LinearGradient, Path, Rect, Stop, Text as SvgText } from 'react-native-svg';

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
  /** the supporter's cap for this relationship */
  limit?: number | null;
};

// soft monogram gradients (light top → deeper bottom), muted so faces read as people, not buttons
const MONO: [string, string][] = [
  ['#5f8fa3', '#3d6577'],
  ['#8a86c2', '#5f5b98'],
  ['#b08ab8', '#80598a'],
  ['#b39370', '#86684a'],
  ['#6ba393', '#467a6b'],
  ['#a3828f', '#765864'],
];
const HAIRLINE = 'rgba(255,255,255,0.14)';
const AMBER = '#f5b74a';
const AV = 30; // avatar radius
const ME = 46; // your avatar radius

const initial = (name: string) => name.trim().charAt(0).toUpperCase();

function subLine(p: CirclePerson): string {
  if (p.status === 'off') return 'Stopped';
  if (p.status === 'waiting') return 'Waiting for a yes';
  return p.role === 'supporter' ? (p.limit ? `Can cover ${money(p.limit, 0)}` : 'Can cover you') : 'You support';
}

export function CircleMap({ me, status, tone, people, selected, onSelect }: {
  me: string;
  status: string;
  tone: string;
  people: CirclePerson[];
  selected: string | null;
  onSelect: (key: string | null) => void;
}) {
  const [width, setWidth] = useState(0);
  const height = Math.min(Math.max(width * 0.72, 330), 400);
  const cx = width / 2;
  const cy = height / 2 - 6;
  const r = Math.min(width * 0.36, height * 0.34);
  const spots = people.map((p, i) => {
    const a = -Math.PI / 2 + (i * 2 * Math.PI) / Math.max(people.length, 1);
    return { p, i, x: cx + r * Math.cos(a), y: cy + r * Math.sin(a) };
  });

  return (
    <View onLayout={(e: LayoutChangeEvent) => setWidth(e.nativeEvent.layout.width)} style={[st.wrap, { height }]}>
      {width > 0 && (
        <>
          <Svg width={width} height={height} style={StyleSheet.absoluteFill}>
            <Defs>
              {MONO.map(([top, bottom], i) => (
                <LinearGradient key={i} id={`mono${i}`} x1="0" y1="0" x2="0" y2="1">
                  <Stop offset="0" stopColor={top} />
                  <Stop offset="1" stopColor={bottom} />
                </LinearGradient>
              ))}
              <LinearGradient id="me" x1="0" y1="0" x2="0" y2="1">
                <Stop offset="0" stopColor="#3a4249" />
                <Stop offset="1" stopColor="#262c31" />
              </LinearGradient>
            </Defs>

            {/* hairline connectors, edge to edge */}
            {spots.map(({ p, x, y }) => {
              const d = Math.hypot(x - cx, y - cy) || 1;
              const ux = (x - cx) / d;
              const uy = (y - cy) / d;
              const on = selected === p.key;
              const color = on ? (p.role === 'supporter' ? C.green : '#7cb8ff') : HAIRLINE;
              return (
                <G key={`c-${p.key}`} opacity={selected && !on ? 0.4 : 1}>
                  <Line x1={cx + ux * (ME + 8)} y1={cy + uy * (ME + 8)} x2={x - ux * (AV + 4)} y2={y - uy * (AV + 4)}
                    stroke={color} strokeWidth={on ? 1.5 : 1} strokeDasharray={p.status === 'active' ? undefined : '3 4'} />
                  {p.out ? <Capsule x={(cx + x) / 2} y={(cy + y) / 2} text={money(p.out, 0)} /> : null}
                </G>
              );
            })}

            {/* you, inside your status ring */}
            <Circle cx={cx} cy={cy} r={ME + 6} stroke={tone} strokeOpacity={0.25} strokeWidth={4} fill="none" />
            <Circle cx={cx} cy={cy} r={ME + 6} stroke={tone} strokeWidth={4} fill="none" strokeLinecap="round"
              strokeDasharray={`${2 * Math.PI * (ME + 6) * 0.82} 999`} transform={`rotate(-90 ${cx} ${cy})`} />
            <Circle cx={cx} cy={cy} r={ME} fill="url(#me)" />
            <SvgText x={cx} y={cy + 9} fill="#fff" fontSize={26} fontFamily={F.bodySemi} textAnchor="middle">{initial(me)}</SvgText>
            <SvgText x={cx} y={cy + ME + 30} fill={C.text} fontSize={16} fontFamily={F.bodySemi} textAnchor="middle">{me}</SvgText>
            <SvgText x={cx} y={cy + ME + 47} fill={tone} fontSize={13} fontFamily={F.bodyMedium} textAnchor="middle">{status}</SvgText>

            {spots.map(({ p, i, x, y }) => {
              const on = selected === p.key;
              const k = on ? 1.08 : 1;
              return (
                <G key={`p-${p.key}`} opacity={selected && !on ? 0.45 : p.status === 'off' ? 0.6 : 1}>
                  {on && <Circle cx={x} cy={y} r={AV * k + 4} stroke="#fff" strokeOpacity={0.9} strokeWidth={2} fill="none" />}
                  <Circle cx={x} cy={y} r={AV * k} fill={`url(#mono${i % MONO.length})`} />
                  <SvgText x={x} y={y + 7} fill="#fff" fontSize={20} fontFamily={F.bodySemi} textAnchor="middle">{initial(p.name)}</SvgText>
                  <Badge x={x + AV * 0.72} y={y + AV * 0.72} status={p.status} />
                  <SvgText x={x} y={y + AV + 20} fill={C.text} fontSize={14} fontFamily={F.bodySemi} textAnchor="middle">{p.name}</SvgText>
                  <SvgText x={x} y={y + AV + 36} fill={C.text2} fontSize={12} fontFamily={F.body} textAnchor="middle">{subLine(p)}</SvgText>
                </G>
              );
            })}
          </Svg>

          {/* hit areas: real buttons for touch, keyboard and screen readers */}
          <Pressable onPress={() => onSelect(null)} accessibilityRole="button" accessibilityLabel={`${me}, ${status}`}
            style={[st.hit, { left: cx - ME - 8, top: cy - ME - 8, width: (ME + 8) * 2, height: (ME + 8) * 2 + 50 }]} />
          {spots.map(({ p, x, y }) => (
            <Pressable key={`h-${p.key}`} onPress={() => onSelect(selected === p.key ? null : p.key)}
              accessibilityRole="button" accessibilityState={{ selected: selected === p.key }}
              accessibilityLabel={`${p.name}: ${p.role === 'supporter' ? 'can cover you' : 'you support them'}, ${subLine(p)}`}
              style={({ pressed }) => [st.hit, { left: x - 46, top: y - AV - 6, width: 92, height: AV * 2 + 50 }, pressed && st.pressed]} />
          ))}
        </>
      )}
    </View>
  );
}

/** The small status badge on an avatar: green check (agreed), amber dots (waiting), grey dash (stopped). */
function Badge({ x, y, status }: { x: number; y: number; status: CirclePerson['status'] }) {
  const fill = status === 'active' ? C.green : status === 'waiting' ? AMBER : C.text3;
  return (
    <G>
      <Circle cx={x} cy={y} r={9} fill={fill} stroke={C.card} strokeWidth={2.5} />
      {status === 'active' && (
        <Path d={`M${x - 3.6},${y + 0.2} L${x - 1},${y + 2.8} L${x + 3.8},${y - 2.6}`} stroke="#0d1a12" strokeWidth={1.8}
          fill="none" strokeLinecap="round" strokeLinejoin="round" />
      )}
      {status === 'waiting' && [-3, 0, 3].map((dx) => <Circle key={dx} cx={x + dx} cy={y} r={1.1} fill="#2a1d05" />)}
      {status === 'off' && <Line x1={x - 3.5} y1={y} x2={x + 3.5} y2={y} stroke="#111" strokeWidth={1.8} strokeLinecap="round" />}
    </G>
  );
}

/** Money out right now, on its connector: a small capsule over the line. */
function Capsule({ x, y, text }: { x: number; y: number; text: string }) {
  const w = 10 + text.length * 7.5;
  return (
    <G>
      <Rect x={x - w / 2} y={y - 11} width={w} height={22} rx={11} fill={C.card2} stroke={HAIRLINE} strokeWidth={1} />
      <SvgText x={x} y={y + 4.5} fill={C.text} fontSize={12} fontFamily={F.bodySemi} textAnchor="middle">{text}</SvgText>
    </G>
  );
}

export function CircleLegend() {
  return (
    <Text style={st.legend}>Tap someone to see what you’ve agreed. Nobody here can see your balance.</Text>
  );
}

const st = StyleSheet.create({
  wrap: { width: '100%', marginTop: 4 },
  hit: { position: 'absolute', borderRadius: 24 },
  pressed: { backgroundColor: 'rgba(255,255,255,0.05)' },
  legend: { fontFamily: F.body, fontSize: 12, lineHeight: 17, color: C.text2, textAlign: 'center', marginTop: 2 },
});

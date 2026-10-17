/**
 * Runway's building blocks: text styles, cards, badges, buttons and the page container.
 * Everything visual comes from constants/runway.ts so the three screens stay one system.
 */
import type { PropsWithChildren, ReactNode } from 'react';
import {
  ActivityIndicator,
  Platform,
  Pressable,
  type PressableProps,
  type StyleProp,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  type TextProps,
  useWindowDimensions,
  View,
  type ViewStyle,
} from 'react-native';
import Animated, { Easing, useAnimatedStyle, useReducedMotion, useSharedValue, withTiming } from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Svg, { Defs, LinearGradient, Rect, Stop } from 'react-native-svg';

import { C, F, MAX_WIDTH, RADIUS, WIDE } from '@/constants/runway';

/** True on the desktop website (and tablets in landscape). */
export const useWide = () => useWindowDimensions().width >= WIDE;

/* ---------------- text ---------------- */

type Tone = 'default' | 'dim' | 'faint' | 'red' | 'green' | 'amber' | 'blue';
const TONE: Record<Tone, string> = { default: C.text, dim: C.text2, faint: C.text3, red: C.red, green: C.green, amber: C.amber, blue: C.blue };

/** Body text (Barlow). */
export function T({ tone = 'default', style, ...p }: TextProps & { tone?: Tone }) {
  return <Text {...p} style={[s.body, { color: TONE[tone] }, style]} />;
}

/** Uppercase condensed label — card headers, statuses, axis labels. */
export function Caps({ tone = 'default', size = 15, style, ...p }: TextProps & { tone?: Tone; size?: number }) {
  return <Text {...p} style={[s.caps, { color: TONE[tone], fontSize: size }, style]} />;
}

/** Big condensed number. */
export function Num({ tone = 'default', size = 34, style, ...p }: TextProps & { tone?: Tone; size?: number }) {
  return <Text {...p} style={[s.num, { color: TONE[tone], fontSize: size, lineHeight: size * 1.05 }, style]} />;
}

/* ---------------- surfaces ---------------- */

export function Card({ children, style }: PropsWithChildren<{ style?: StyleProp<ViewStyle> }>) {
  return <View style={[s.card, style]}>{children}</View>;
}

/** Uppercase card title with an optional chevron or right-side element. */
export function CardHeader({ title, right, chevron = false }: { title: string; right?: ReactNode; chevron?: boolean }) {
  return (
    <View style={s.cardHd}>
      <Caps style={{ flexShrink: 1 }}>{title}</Caps>
      {right ?? (chevron ? <Caps tone="dim" size={20} style={{ lineHeight: 18 }}>›</Caps> : null)}
    </View>
  );
}

/** Tinted square with a short value or glyph, as in "! BELOW FLOOR". */
export function Badge({ tone, children }: PropsWithChildren<{ tone: 'red' | 'green' | 'amber' | 'blue' }>) {
  return (
    <View style={[s.badge, { backgroundColor: `${TONE[tone]}29` }]}>
      <Caps tone={tone} size={14} style={{ letterSpacing: 0.4 }}>{children}</Caps>
    </View>
  );
}

/** Section title between cards ("My Runway"). */
export function SectionTitle({ children }: PropsWithChildren) {
  return <Text style={s.section}>{children}</Text>;
}

/* ---------------- buttons ---------------- */

const EASE_OUT = Easing.bezier(0.23, 1, 0.32, 1);

/** Merges a style prop (object, array, falsy entries) into one object. StyleSheet.create returns plain objects. */
function mergeStyle(style: StyleProp<ViewStyle>): ViewStyle {
  return Object.assign({}, ...[style].flat(Infinity as 1).filter(Boolean)) as ViewStyle;
}

/** Scales to 0.97 on press-in (feedback before release); 120ms ease-out, skipped with reduced motion. */
export function PressableScale({ style, children, ...p }: Omit<PressableProps, 'style'> & { style?: StyleProp<ViewStyle> }) {
  const reduced = useReducedMotion();
  const scale = useSharedValue(1);
  const anim = useAnimatedStyle(() => ({ transform: [{ scale: scale.get() }] }));
  // Sizing in the parent's layout (flex: 1 in a row, width…) has to live on the outer Pressable,
  // or the button collapses to its content; everything visual stays on the scaled layer.
  const flat = mergeStyle(style);
  const { flex, flexGrow, flexShrink, flexBasis, alignSelf, width, minWidth, maxWidth, ...visual } = flat;
  const outer: ViewStyle = { flex, flexGrow, flexShrink, flexBasis, alignSelf, width, minWidth, maxWidth };
  const fill = flex !== undefined || flexGrow !== undefined || width !== undefined;
  return (
    <Pressable
      {...p}
      style={outer}
      hitSlop={8}
      onPressIn={(e) => {
        if (!reduced) scale.set(withTiming(0.97, { duration: 120, easing: EASE_OUT }));
        p.onPressIn?.(e);
      }}
      onPressOut={(e) => {
        scale.set(withTiming(1, { duration: 120, easing: EASE_OUT }));
        p.onPressOut?.(e);
      }}>
      <Animated.View style={[visual, fill && { flexGrow: 1 }, anim]}>{children as ReactNode}</Animated.View>
    </Pressable>
  );
}

/** Pill button: white primary, outlined ghost. */
export function Btn({ label, ghost, disabled, onPress, style }: { label: string; ghost?: boolean; disabled?: boolean; onPress?: () => void; style?: StyleProp<ViewStyle> }) {
  return (
    <PressableScale onPress={onPress} disabled={disabled} accessibilityRole="button" style={[s.btn, ghost && s.btnGhost, disabled && { opacity: 0.55 }, style]}>
      <Caps size={15} style={{ color: ghost ? C.text2 : '#111', letterSpacing: 1.5 }}>{label}</Caps>
    </PressableScale>
  );
}

/* ---------------- page ---------------- */

/**
 * Scrollable page: charcoal gradient, safe-area top padding on phones, centred max-width column on
 * desktop. `header` sits above the scroll on the website's wide layout only if provided.
 */
export function Page({ children, onRefresh, refreshing = false, scroll = true, backdrop }: PropsWithChildren<{
  onRefresh?: () => void; refreshing?: boolean; scroll?: boolean;
  /** drawn over the gradient, behind the content, full width (e.g. Today's glows) */
  backdrop?: ReactNode;
}>) {
  const insets = useSafeAreaInsets();
  const wide = useWide();
  const top = Platform.OS === 'web' ? (wide ? 24 : 12) : insets.top + 8;
  const inner = <View style={[s.inner, { paddingTop: top, paddingHorizontal: wide ? 32 : 12 }]}>{children}</View>;
  return (
    <View style={s.page}>
      <Svg style={StyleSheet.absoluteFill} preserveAspectRatio="none" viewBox="0 0 100 100" pointerEvents="none">
        <Defs>
          <LinearGradient id="pg" x1="0" y1="0" x2="0" y2="1">
            <Stop offset="0" stopColor={C.bgTop} />
            <Stop offset="0.35" stopColor="#1a2026" />
            <Stop offset="0.7" stopColor={C.bg} />
          </LinearGradient>
        </Defs>
        <Rect width="100" height="100" fill="url(#pg)" />
      </Svg>
      {backdrop}
      {scroll ? (
        <ScrollView
          contentContainerStyle={{ paddingBottom: 124 }} // room for the floating bottom bar / chat button
          refreshControl={onRefresh ? <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={C.text2} /> : undefined}>
          {inner}
        </ScrollView>
      ) : (
        <View style={{ flex: 1 }}>{inner}</View>
      )}
    </View>
  );
}

/** Loading / error placeholder for a screen or card. */
export function LoadState({ error, onRetry }: { error?: string | null; onRetry?: () => void }) {
  if (!error) return <View style={s.state}><ActivityIndicator color={C.text2} /></View>;
  return (
    <Card style={[s.state, { gap: 10 }]}>
      <Caps tone="red">Can&apos;t reach Runway</Caps>
      <T tone="dim" style={{ textAlign: 'center' }}>The server didn&apos;t answer. Check your connection and try again.</T>
      {onRetry && <Btn label="Try again" ghost onPress={onRetry} />}
    </Card>
  );
}

const s = StyleSheet.create({
  body: { fontFamily: F.body, fontSize: 15, lineHeight: 21 },
  caps: { fontFamily: F.cond, textTransform: 'uppercase', letterSpacing: 1.2 },
  num: { fontFamily: F.condBold, fontVariant: ['tabular-nums'] },
  card: { backgroundColor: C.card, borderRadius: RADIUS, padding: 16 },
  cardHd: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 },
  badge: { width: 34, height: 34, borderRadius: 7, alignItems: 'center', justifyContent: 'center' },
  section: { fontFamily: F.cond, fontSize: 26, color: C.text, paddingTop: 24, paddingBottom: 10, paddingHorizontal: 4 },
  btn: { height: 40, paddingHorizontal: 18, borderRadius: 999, backgroundColor: '#fff', alignItems: 'center', justifyContent: 'center' },
  btnGhost: { backgroundColor: 'transparent', borderWidth: 1, borderColor: C.line },
  page: { flex: 1, backgroundColor: C.bg, overflow: 'hidden' },
  inner: { width: '100%', maxWidth: MAX_WIDTH, alignSelf: 'center', flex: 1 },
  state: { padding: 32, alignItems: 'center', justifyContent: 'center' },
});

/**
 * The list look shared by Today, Spending and Family: a spaced-caps section label, a rounded card,
 * and rows separated by hairlines (avatar or icon · title over a dim line · something on the right).
 */
import type { PropsWithChildren, ReactNode } from 'react';
import { StyleSheet, Text, View, type ViewStyle } from 'react-native';

import { alpha, C, F } from '@/constants/runway';

/** "COMING UP", "YOUR LIMITS" — sits above a list card. */
export function SectionLabel({ children, first }: PropsWithChildren<{ first?: boolean }>) {
  return <Text style={[s.label, first && { marginTop: 18 }]} accessibilityRole="header">{children}</Text>;
}

/** The rounded card rows sit in. */
export function List({ children, style }: PropsWithChildren<{ style?: ViewStyle }>) {
  return <View style={[s.list, style]}>{children}</View>;
}

/** One row. `first` drops the hairline above it. */
export function Row({ first, left, title, sub, right, highlight }: {
  first?: boolean; left?: ReactNode; title: string; sub?: string; right?: ReactNode; highlight?: boolean;
}) {
  return (
    <View style={[s.row, !first && s.rowLine, highlight && s.rowOn]}>
      {left}
      <View style={{ flex: 1, minWidth: 0 }}>
        <Text style={s.title} numberOfLines={2}>{title}</Text>
        {sub ? <Text style={s.sub} numberOfLines={2}>{sub}</Text> : null}
      </View>
      {right}
    </View>
  );
}

/** A round initial ("M") or a glyph in a soft circle. */
export function Avatar({ name, children, tint }: PropsWithChildren<{ name?: string; tint?: string }>) {
  return (
    <View style={[s.avatar, tint ? { backgroundColor: alpha(tint, '26') } : null]}>
      {children ?? <Text style={s.initial}>{name?.[0] ?? '?'}</Text>}
    </View>
  );
}

/** A right-aligned amount in the condensed face ("$45", "+$780"). */
export function Amount({ children, tone }: PropsWithChildren<{ tone?: 'green' | 'red' | 'dim' }>) {
  const color = tone === 'green' ? C.green : tone === 'red' ? C.red : tone === 'dim' ? C.text2 : C.text;
  return <Text style={[s.amount, { color }]}>{children}</Text>;
}

/** Small print under a list. */
export function Fine({ children }: PropsWithChildren) {
  return <Text style={s.fine}>{children}</Text>;
}

const s = StyleSheet.create({
  label: { fontFamily: F.cond, fontSize: 13, letterSpacing: 1.8, textTransform: 'uppercase', color: C.text2, marginTop: 28, marginBottom: 10, marginHorizontal: 2 },
  list: { borderRadius: 20, backgroundColor: C.card, paddingHorizontal: 14, paddingVertical: 2 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 12 },
  rowLine: { borderTopWidth: 1, borderTopColor: C.line },
  rowOn: { backgroundColor: C.hover, marginHorizontal: -14, paddingHorizontal: 14 },
  title: { fontFamily: F.bodySemi, fontSize: 16, color: C.text },
  sub: { fontFamily: F.body, fontSize: 13, color: C.text2, marginTop: 1 },
  avatar: { width: 38, height: 38, borderRadius: 19, backgroundColor: C.card2, alignItems: 'center', justifyContent: 'center' },
  initial: { fontFamily: F.bodySemi, fontSize: 15, color: C.text2 },
  amount: { fontFamily: F.condBold, fontSize: 18, letterSpacing: 0.3, fontVariant: ['tabular-nums'] },
  fine: { fontFamily: F.body, fontSize: 12, lineHeight: 17, color: C.text3, marginTop: 10, marginHorizontal: 2 },
});

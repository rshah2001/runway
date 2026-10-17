import { StyleSheet, View } from 'react-native';

import { C, F, KIND_COLOR } from '@/constants/runway';

import { Icon } from './icons';
import { Caps, T } from './ui';

/**
 * WHOOP-style activity row: a coloured pill (icon + amount), an uppercase title with a small
 * subtitle, and a two-line right column (e.g. "THU" / "Oct 22", or "34%" / "of total").
 */
export function ActRow({ kind, amount, title, subtitle, rightTop, rightBottom }: {
  kind: string; amount: string; title: string; subtitle?: string; rightTop?: string; rightBottom?: string;
}) {
  return (
    <View style={s.row}>
      <View style={[s.pill, { backgroundColor: KIND_COLOR[kind] ?? KIND_COLOR.other }]}>
        <Icon name={kind} size={18} color="#fff" />
        <T style={s.pillText} numberOfLines={1}>{amount}</T>
      </View>
      <View style={{ flex: 1, minWidth: 0 }}>
        <Caps size={15} numberOfLines={1}>{title}</Caps>
        {subtitle ? <Caps tone="dim" size={12} style={{ marginTop: 2, fontFamily: F.condMedium }} numberOfLines={1}>{subtitle}</Caps> : null}
      </View>
      {rightTop ? (
        <View style={{ alignItems: 'flex-end' }}>
          <Caps size={13}>{rightTop}</Caps>
          {rightBottom ? <Caps tone="dim" size={13}>{rightBottom}</Caps> : null}
        </View>
      ) : null}
    </View>
  );
}

const s = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', gap: 14, padding: 10, borderRadius: 10, backgroundColor: C.card2 },
  pill: { width: 112, height: 44, borderRadius: 8, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8 },
  pillText: { fontFamily: F.condBold, fontSize: 20, lineHeight: 24, color: '#fff' },
});

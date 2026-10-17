/**
 * The top of every phone screen: the Runway wordmark and "Hi, Name ⌄". On the desktop website the
 * same two live in the top bar (components/app-tabs.tsx), so this renders nothing there.
 * `PageTitle` is the big screen name under it ("Family", "Spending") with one line of context.
 */
import { StyleSheet, Text, View } from 'react-native';

import { AccountMenu } from '@/components/login/account-menu';
import { C, F } from '@/constants/runway';

import { Swoosh } from './icons';
import { useWide } from './ui';

export function TopBar() {
  const wide = useWide();
  if (wide) return null;
  return (
    <View style={s.top}>
      <View style={s.brand}><Swoosh /><Text style={s.word}>RUNWAY</Text></View>
      <AccountMenu />
    </View>
  );
}

export function PageTitle({ title, sub }: { title: string; sub?: string }) {
  return (
    <View style={{ marginTop: 26 }}>
      <Text style={s.title} accessibilityRole="header">{title}</Text>
      {sub ? <Text style={s.sub}>{sub}</Text> : null}
    </View>
  );
}

const s = StyleSheet.create({
  top: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingTop: 8, paddingHorizontal: 4 },
  brand: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  word: { fontFamily: F.cond, fontSize: 16, letterSpacing: 5, color: C.text },
  title: { fontFamily: F.bodySemi, fontSize: 30, letterSpacing: -0.6, color: C.text, paddingHorizontal: 2 },
  sub: { fontFamily: F.body, fontSize: 15, lineHeight: 21, color: C.text2, marginTop: 6, paddingHorizontal: 2 },
});

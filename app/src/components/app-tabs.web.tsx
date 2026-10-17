// Website navigation. Desktop: a top bar with the wordmark and tabs. Phone browsers: a bottom tab
// bar like the app. Built on expo-router/ui so routes and focus state come from the router.
import { TabList, type TabListProps, TabSlot, TabTrigger, type TabTriggerSlotProps, Tabs } from 'expo-router/ui';
import { type ComponentRef, forwardRef } from 'react';
import { Pressable, type PressableStateCallbackType, StyleSheet, View } from 'react-native';
import Svg, { Path } from 'react-native-svg';

import { AccountButton } from '@/components/login/account-button';
import { Swoosh } from '@/components/rw/icons';
import { Caps, useWide } from '@/components/rw/ui';
import { C, F, MAX_WIDTH } from '@/constants/runway';

const ICON: Record<string, string> = {
  today: 'M4 10.5L12 4l8 6.5V20H4zM8 16l2.5-2.5 2 2L16 12',
  ask: 'M4 5.5h16v10H9l-5 3.5z',
  spending: 'M5 19V11M10 19V6M15 19v-9M20 19v-5',
};

export default function AppTabs() {
  const wide = useWide();
  const list = (
    <TabList asChild>
      <Bar wide={wide}>
        <TabTrigger name="today" href="/" asChild><Tab icon="today" wide={wide}>Today</Tab></TabTrigger>
        <TabTrigger name="ask" href="/ask" asChild><Tab icon="ask" wide={wide}>Ask</Tab></TabTrigger>
        <TabTrigger name="spending" href="/spending" asChild><Tab icon="spending" wide={wide}>Spending</Tab></TabTrigger>
      </Bar>
    </TabList>
  );
  return (
    <Tabs style={{ flex: 1, backgroundColor: C.bg }}>
      {wide && list}
      <TabSlot style={{ flex: 1 }} />
      {!wide && list}
    </Tabs>
  );
}

const Bar = forwardRef<ComponentRef<typeof View>, TabListProps & { wide: boolean }>(function Bar({ wide, children, ...props }, ref) {
  if (!wide) return <View ref={ref} {...props} style={s.bottom}>{children}</View>;
  return (
    <View ref={ref} {...props} style={s.topWrap}>
      <View style={s.top}>
        <View style={s.brand}><Swoosh /><Caps size={20} style={{ letterSpacing: 7, fontFamily: F.condMedium }}>Runway</Caps></View>
        <View style={s.right}>
          <View style={s.links}>{children}</View>
          <AccountButton />
        </View>
      </View>
    </View>
  );
});

const Tab = forwardRef<ComponentRef<typeof View>, TabTriggerSlotProps & { icon: string; wide: boolean }>(function Tab({ icon, wide, isFocused, children, ...props }, ref) {
  const color = isFocused ? C.text : C.text3;
  return (
    <Pressable ref={ref} {...props} style={({ hovered }: PressableStateCallbackType & { hovered?: boolean }) => [wide ? s.topTab : s.bottomTab, wide && (isFocused || hovered) && { backgroundColor: isFocused ? C.card2 : C.card }]}>
      <Svg width={wide ? 18 : 24} height={wide ? 18 : 24} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
        <Path d={ICON[icon]} />
      </Svg>
      <Caps size={wide ? 14 : 11} style={{ color, letterSpacing: wide ? 1.6 : 0.6, fontFamily: wide ? F.cond : F.bodyMedium, textTransform: wide ? 'uppercase' : 'none' }}>
        {children as string}
      </Caps>
    </Pressable>
  );
});

const s = StyleSheet.create({
  topWrap: { backgroundColor: C.tabBar, borderBottomWidth: 1, borderBottomColor: '#20262c' },
  top: { width: '100%', maxWidth: MAX_WIDTH, alignSelf: 'center', flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 32, height: 64 },
  brand: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  links: { flexDirection: 'row', gap: 6 },
  right: { flexDirection: 'row', alignItems: 'center', gap: 18 },
  topTab: { flexDirection: 'row', alignItems: 'center', gap: 8, height: 38, paddingHorizontal: 14, borderRadius: 999 },
  bottom: { flexDirection: 'row', justifyContent: 'space-around', paddingTop: 10, paddingBottom: 18, backgroundColor: C.tabBar, borderTopWidth: 1, borderTopColor: '#20262c' },
  bottomTab: { alignItems: 'center', gap: 4, minWidth: 72 },
});

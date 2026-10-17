// Navigation for every platform, built on expo-router/ui so routes and focus come from the router.
//  - Phones (Android, iOS, phone browsers): a floating pill with icon-only tabs, and the round chat
//    button beside it.
//  - Desktop website: a top bar with the wordmark, tabs and account; chat lives in the corner window.
// Tab switches don't animate (tabs are peers, used dozens of times a session); only press feedback.
import { TabList, type TabListProps, TabSlot, TabTrigger, type TabTriggerSlotProps, Tabs } from 'expo-router/ui';
import { type ComponentRef, forwardRef } from 'react';
import { Platform, Pressable, type PressableStateCallbackType, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Svg, { Path } from 'react-native-svg';

import { AccountButton } from '@/components/login/account-button';
import { openChat } from '@/components/rw/chat';
import { Swoosh } from '@/components/rw/icons';
import { Caps, PressableScale, useWide } from '@/components/rw/ui';
import { C, F, MAX_WIDTH } from '@/constants/runway';

const ICON: Record<string, { d: string; fill?: boolean }> = {
  today: { d: 'M12 3.2 3 10.4V20a1 1 0 0 0 1 1h5.5v-6h5v6H20a1 1 0 0 0 1-1v-9.6z', fill: true },
  spending: { d: 'M5 20v-7M10 20V5M15 20v-9M20 20v-4' },
};

export default function AppTabs() {
  const wide = useWide();
  const list = (
    <TabList asChild>
      <Bar wide={wide}>
        <TabTrigger name="today" href="/" asChild><Tab icon="today" wide={wide}>Today</Tab></TabTrigger>
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

/** Phones: the pill + chat button float over the page. Desktop: the top bar. */
const Bar = forwardRef<ComponentRef<typeof View>, TabListProps & { wide: boolean }>(function Bar({ wide, children, ...props }, ref) {
  const insets = useSafeAreaInsets();
  if (!wide) {
    const bottom = Platform.OS === 'web' ? ('max(18px, env(safe-area-inset-bottom))' as unknown as number) : Math.max(14, insets.bottom);
    return (
      <View style={[s.dock, { bottom }]} pointerEvents="box-none">
        <View ref={ref} {...props} style={s.pill}>{children}</View>
        <PressableScale onPress={openChat} style={s.chat} accessibilityRole="button" accessibilityLabel="Ask Runway">
          <Svg width={26} height={26} viewBox="0 0 24 24" fill="none" stroke="#111" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
            <Path d="M4 5.5h16v10H9l-5 3.5z" /><Path d="M8 9.5h8M8 12.5h5" />
          </Svg>
        </PressableScale>
      </View>
    );
  }
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
  const { d, fill } = ICON[icon];
  const color = isFocused ? C.text : wide ? C.text3 : '#8f979e';
  const glyph = (
    <Svg width={wide ? 18 : 26} height={wide ? 18 : 26} viewBox="0 0 24 24" fill={fill ? color : 'none'} stroke={fill ? 'none' : color} strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round">
      <Path d={d} />
    </Svg>
  );
  if (!wide) {
    return (
      <Pressable ref={ref} {...props} accessibilityLabel={children as string} style={({ pressed }) => [s.pillTab, isFocused && s.pillTabOn, pressed && { opacity: 0.8 }]}>
        {glyph}
      </Pressable>
    );
  }
  return (
    <Pressable ref={ref} {...props} style={({ hovered }: PressableStateCallbackType & { hovered?: boolean }) => [s.topTab, (isFocused || hovered) && { backgroundColor: isFocused ? C.card2 : C.card }]}>
      {glyph}
      <Caps size={14} style={{ color, letterSpacing: 1.6 }}>{children as string}</Caps>
    </Pressable>
  );
});

const s = StyleSheet.create({
  dock: { position: 'absolute', left: 16, right: 16, flexDirection: 'row', alignItems: 'center', gap: 12 },
  pill: {
    flex: 1, height: 66, padding: 5, borderRadius: 33, flexDirection: 'row', alignItems: 'center',
    backgroundColor: Platform.OS === 'web' ? 'rgba(52,56,60,0.72)' : 'rgba(44,48,52,0.97)',
    borderWidth: 1, borderColor: 'rgba(255,255,255,0.08)',
    shadowColor: '#000', shadowOpacity: 0.45, shadowRadius: 20, shadowOffset: { width: 0, height: 10 }, elevation: 12,
    // frosted glass where the platform supports it (web); a near-opaque fill elsewhere
    ...(Platform.OS === 'web' ? ({ backdropFilter: 'blur(20px) saturate(1.6)' } as object) : {}),
  },
  pillTab: { flex: 1, height: '100%', borderRadius: 28, alignItems: 'center', justifyContent: 'center' },
  pillTabOn: { backgroundColor: '#16191c' },
  chat: { width: 66, height: 66, borderRadius: 33, backgroundColor: '#e6e8ea', alignItems: 'center', justifyContent: 'center',
    shadowColor: '#000', shadowOpacity: 0.45, shadowRadius: 20, shadowOffset: { width: 0, height: 10 }, elevation: 12 },
  topWrap: { backgroundColor: C.tabBar, borderBottomWidth: 1, borderBottomColor: '#20262c' },
  top: { width: '100%', maxWidth: MAX_WIDTH, alignSelf: 'center', flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 32, height: 64 },
  brand: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  right: { flexDirection: 'row', alignItems: 'center', gap: 18 },
  links: { flexDirection: 'row', gap: 6 },
  topTab: { flexDirection: 'row', alignItems: 'center', gap: 8, height: 38, paddingHorizontal: 14, borderRadius: 999 },
});

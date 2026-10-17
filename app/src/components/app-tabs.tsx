// Native tab bar (Android / iOS): the platform's real tabs, in Runway's charcoal palette.
// Tab switches don't animate — tabs are peers, and they're used dozens of times a session.
import { NativeTabs } from 'expo-router/native-tabs';

import { C, F } from '@/constants/runway';

export default function AppTabs() {
  return (
    <NativeTabs
      backgroundColor={C.tabBar}
      indicatorColor={C.card2}
      iconColor={{ default: C.text3, selected: C.text }}
      labelStyle={{ default: { color: C.text3, fontFamily: F.bodyMedium }, selected: { color: C.text, fontFamily: F.bodyMedium } }}>
      <NativeTabs.Trigger name="index">
        <NativeTabs.Trigger.Label>Today</NativeTabs.Trigger.Label>
        <NativeTabs.Trigger.Icon sf="house" md="home" />
      </NativeTabs.Trigger>

      <NativeTabs.Trigger name="spending">
        <NativeTabs.Trigger.Label>Spending</NativeTabs.Trigger.Label>
        <NativeTabs.Trigger.Icon sf="chart.bar" md="bar_chart" />
      </NativeTabs.Trigger>
    </NativeTabs>
  );
}

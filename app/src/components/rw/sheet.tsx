/**
 * A bottom sheet over a dimmed page: the approval sheet and, on phones, the chat.
 * It rises from the bottom and leaves the same way (iOS sheet curve, 420ms in / 300ms out); the page
 * behind dims so the decision has your full attention. Tap the dim area, press Escape or Android back
 * to close. Reduced motion: fades only. On the desktop website it sits centred, no wider than 520px.
 */
import { type PropsWithChildren, useEffect, useState } from 'react';
import { BackHandler, Platform, Pressable, StyleSheet, useWindowDimensions, View, type ViewStyle } from 'react-native';
import Animated, { Easing, useAnimatedStyle, useReducedMotion, useSharedValue, withTiming } from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { scheduleOnRN } from 'react-native-worklets';

import { C } from '@/constants/runway';
import { zoom } from '@/lib/zoom';

import { useWide } from './ui';

const EASE_SHEET = Easing.bezier(0.32, 0.72, 0, 1);

export function Sheet({ open, onClose, label, style, children }: PropsWithChildren<{
  open: boolean;
  onClose: () => void;
  /** what a screen reader announces for the sheet */
  label: string;
  style?: ViewStyle;
}>) {
  const reduced = useReducedMotion();
  const wide = useWide();
  const insets = useSafeAreaInsets();
  const height = useWindowDimensions().height / zoom(); // layout px on the scaled desktop site
  const p = useSharedValue(0); // 0 closed … 1 open
  const [mounted, setMounted] = useState(open);

  if (open && !mounted) setMounted(true);

  useEffect(() => {
    if (!mounted) return;
    p.set(withTiming(open ? 1 : 0, { duration: open ? 420 : 300, easing: EASE_SHEET }, (done) => {
      if (done && !open) scheduleOnRN(setMounted, false); // unmount once it has fully left
    }));
  }, [open, mounted, p]);

  useEffect(() => {
    if (!open) return;
    const sub = BackHandler.addEventListener('hardwareBackPress', () => (onClose(), true));
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    if (Platform.OS === 'web') window.addEventListener('keydown', onKey);
    return () => {
      sub.remove();
      if (Platform.OS === 'web') window.removeEventListener('keydown', onKey);
    };
  }, [open, onClose]);

  const scrim = useAnimatedStyle(() => ({ opacity: p.get() * 0.55 }));
  const panel = useAnimatedStyle(() => (reduced
    ? { opacity: p.get() }
    : { transform: [{ translateY: (1 - p.get()) * Math.min(height, 900) }] }));

  if (!mounted) return null;
  return (
    <View style={StyleSheet.absoluteFill} pointerEvents={open ? 'auto' : 'none'}>
      <Animated.View style={[StyleSheet.absoluteFill, s.scrim, scrim]}>
        <Pressable style={StyleSheet.absoluteFill} onPress={onClose} accessibilityRole="button" accessibilityLabel="Close" />
      </Animated.View>
      <Animated.View accessibilityViewIsModal accessibilityLabel={label}
        style={[s.panel, wide && s.panelWide, { paddingBottom: Math.max(24, insets.bottom + 12), maxHeight: height * 0.88 }, style, panel]}>
        <Pressable onPress={onClose} style={s.grabHit} accessibilityRole="button" accessibilityLabel="Close">
          <View style={s.grab} />
        </Pressable>
        {children}
      </Animated.View>
    </View>
  );
}

const s = StyleSheet.create({
  scrim: { backgroundColor: '#000' },
  panel: {
    position: 'absolute', left: 0, right: 0, bottom: 0, backgroundColor: C.card,
    borderTopLeftRadius: 28, borderTopRightRadius: 28, paddingHorizontal: 20,
    shadowColor: '#000', shadowOpacity: 0.4, shadowRadius: 30, shadowOffset: { width: 0, height: -8 }, elevation: 24,
  },
  panelWide: { left: '50%', width: 520, marginLeft: -260, bottom: 24, borderRadius: 28 },
  grabHit: { alignSelf: 'center', paddingTop: 10, paddingBottom: 14, paddingHorizontal: 30 },
  grab: { width: 38, height: 5, borderRadius: 3, backgroundColor: '#3a4147' },
});

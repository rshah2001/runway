/**
 * "Hi, Maya ⌄" — who you are, and the way out. Tapping it opens a small menu that grows from the
 * button (name, how you signed in, Sign out); any tap outside or Escape closes it.
 * It replaces the plain "Maya · Sign out" chip (account-button.tsx) at the top of Today and on desktop.
 */
import { type ComponentRef, useRef, useState } from 'react';
import { Dimensions, Modal, Pressable, StyleSheet, Text, View } from 'react-native';
import Animated, { Easing, FadeOut, Keyframe } from 'react-native-reanimated';
import Svg, { Path } from 'react-native-svg';

import { PressableScale } from '@/components/rw/ui';
import { C, F } from '@/constants/runway';
import { leave } from '@/lib/account';
import { useSession } from '@/lib/session';

// grows from the button's top-right corner: scale 0.92 → 1 with a quick fade (Apple: anchor to the source)
const GROW = new Keyframe({
  0: { opacity: 0, transform: [{ scale: 0.92 }] },
  100: { opacity: 1, transform: [{ scale: 1 }], easing: Easing.bezier(0.23, 1, 0.32, 1) },
}).duration(220);

export function AccountMenu() {
  const session = useSession();
  const button = useRef<ComponentRef<typeof View>>(null);
  const [at, setAt] = useState<{ top: number; right: number } | null>(null);
  const [leaving, setLeaving] = useState(false);
  if (session.mode !== 'signed-in') return null;
  const name = session.name ?? 'there';

  function open() {
    // place the menu under the button, right edges lined up
    button.current?.measureInWindow((x, y, w, h) => {
      const vw = Dimensions.get('window').width;
      setAt({ top: y + h + 8, right: Math.max(8, vw - (x + w)) });
    });
  }

  async function signOut() {
    setLeaving(true);
    try {
      await leave();
    } finally {
      setLeaving(false);
      setAt(null);
    }
  }

  return (
    <>
      <View ref={button} collapsable={false}>
        <PressableScale onPress={open} accessibilityRole="button" accessibilityLabel={`Signed in as ${name}. Account menu`}
          accessibilityState={{ expanded: !!at }} style={s.hi}>
          <Text style={s.hiText}>Hi, {name}</Text>
          <Svg width={12} height={12} viewBox="0 0 24 24" fill="none" stroke={C.text} strokeWidth={3} strokeLinecap="round" strokeLinejoin="round"
            style={at ? { transform: [{ rotate: '180deg' }] } : undefined}>
            <Path d="m6 9 6 6 6-6" />
          </Svg>
        </PressableScale>
      </View>
      <Modal transparent visible={!!at} onRequestClose={() => setAt(null)} animationType="none">
        <Pressable style={StyleSheet.absoluteFill} onPress={() => setAt(null)} accessibilityLabel="Close menu" />
        {at && (
          <Animated.View entering={GROW} exiting={FadeOut.duration(120)} style={[s.menu, { top: at.top, right: at.right }]} accessibilityRole="menu">
            <View style={s.who}>
              <Text style={s.whoName}>{name}</Text>
              <Text style={s.whoSub}>Signed in with Auth0</Text>
            </View>
            <Pressable onPress={signOut} disabled={leaving} accessibilityRole="menuitem"
              style={({ pressed, hovered }: { pressed: boolean; hovered?: boolean }) => [s.item, (pressed || hovered) && { backgroundColor: 'rgba(255,255,255,0.05)' }]}>
              <Svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke={C.red} strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round">
                <Path d="M15 4h4v16h-4M10 8l-4 4 4 4M6 12h10" />
              </Svg>
              <Text style={s.itemText}>{leaving ? 'Signing out…' : 'Sign out'}</Text>
            </Pressable>
          </Animated.View>
        )}
      </Modal>
    </>
  );
}

const s = StyleSheet.create({
  hi: { flexDirection: 'row', alignItems: 'center', gap: 6, height: 36, paddingLeft: 14, paddingRight: 12, borderRadius: 999, backgroundColor: C.card2 },
  hiText: { fontFamily: F.bodySemi, fontSize: 15, color: C.text },
  menu: {
    position: 'absolute', minWidth: 200, padding: 6, borderRadius: 18, backgroundColor: C.card2, transformOrigin: 'top right',
    shadowColor: '#000', shadowOpacity: 0.5, shadowRadius: 40, shadowOffset: { width: 0, height: 14 }, elevation: 20,
  },
  who: { paddingHorizontal: 12, paddingVertical: 10 },
  whoName: { fontFamily: F.bodySemi, fontSize: 15, color: C.text },
  whoSub: { fontFamily: F.body, fontSize: 13, color: C.text2 },
  item: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingHorizontal: 12, paddingVertical: 11, borderRadius: 12, borderTopWidth: 1, borderTopColor: C.line },
  itemText: { fontFamily: F.bodySemi, fontSize: 15, color: C.red },
});

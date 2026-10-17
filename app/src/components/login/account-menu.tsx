/**
 * "Hi, Maya ⌄" — who you are, and the way out. Tapping it opens a small menu that grows from the
 * button (name, how you signed in, the money you keep, Sign out); any tap outside or Escape closes it.
 * "Money I keep" is the cushion every "am I okay?" is measured against — the forecast line, dips,
 * spare money, and when family steps in. People differ (one is anxious under $100, another under
 * $1,000), so each person sets their own; nobody can set it for someone else.
 * It replaces the plain "Maya · Sign out" chip (account-button.tsx) at the top of Today and on desktop.
 */
import { type ComponentRef, useRef, useState } from 'react';
import { Dimensions, Modal, Platform, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import Animated, { Easing, FadeOut, Keyframe } from 'react-native-reanimated';
import Svg, { Path } from 'react-native-svg';

import { Sheet } from '@/components/rw/sheet';
import { PressableScale } from '@/components/rw/ui';
import { C, F } from '@/constants/runway';
import { leave } from '@/lib/account';
import { api } from '@/lib/api';
import { money } from '@/lib/format';
import { setStore, useStore } from '@/lib/store';
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
  const [keep, setKeep] = useState<number | null>(null); // what you keep, read when the menu opens
  const [editing, setEditing] = useState(false); // the "Money I keep" sheet
  if (session.mode !== 'signed-in') return null;
  const name = session.name ?? 'there';

  function open() {
    // place the menu under the button, right edges lined up
    button.current?.measureInWindow((x, y, w, h) => {
      const vw = Dimensions.get('window').width;
      setAt({ top: y + h + 8, right: Math.max(8, vw - (x + w)) });
    });
    // only a real number counts: an older server (or a failed read) shows "…", never a guess
    api.me().then((m) => setKeep(typeof m.safe_floor === 'number' ? m.safe_floor : null)).catch(() => setKeep(null));
  }

  function close() {
    setAt(null);
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
      <Modal transparent visible={!!at} onRequestClose={close} animationType="none">
        <Pressable style={StyleSheet.absoluteFill} onPress={close} accessibilityLabel="Close menu" />
        {at && (
          <Animated.View entering={GROW} exiting={FadeOut.duration(120)} style={[s.menu, { top: at.top, right: at.right }]} accessibilityRole="menu">
            <View style={s.who}>
              <Text style={s.whoName}>{name}</Text>
              <Text style={s.whoSub}>Signed in with Auth0</Text>
            </View>
            {(
              <Pressable onPress={() => { close(); setEditing(true); }} disabled={keep === null} accessibilityRole="menuitem"
                accessibilityLabel={`Money I keep in checking: ${keep === null ? 'loading' : money(keep, 0)}. Change`}
                style={({ pressed, hovered }: { pressed: boolean; hovered?: boolean }) => [s.item, (pressed || hovered) && { backgroundColor: 'rgba(255,255,255,0.05)' }]}>
                <View style={{ flex: 1 }}>
                  <Text style={[s.itemText, { color: C.text }]}>Money I keep</Text>
                  <Text style={s.whoSub}>Runway warns you before you go under it</Text>
                </View>
                <Text style={[s.itemText, { color: C.text2 }]}>{keep === null ? '…' : money(keep, 0)}</Text>
              </Pressable>
            )}
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
      {/* a sheet for the small task of changing it (the menu lives in the top bar, so it gets its own layer) */}
      <Modal transparent visible={editing && keep !== null} onRequestClose={() => setEditing(false)} animationType="none">
        <Sheet open={editing && keep !== null} onClose={() => setEditing(false)} label="Money I keep in checking">
          {keep !== null && (
            <KeepEditor current={keep} onSaved={(v) => { setKeep(v); setEditing(false); }} onCancel={() => setEditing(false)} />
          )}
        </Sheet>
      </Modal>
    </>
  );
}

const PRESETS = [0, 50, 100, 200, 300, 500, 1000];
const MAX_KEEP = 5000; // the server's limit too

/** Pick or type what you keep; saves for you only, then every screen re-fetches its forecast. */
function KeepEditor({ current, onSaved, onCancel }: { current: number; onSaved: (v: number) => void; onCancel: () => void }) {
  const store = useStore();
  const [value, setValue] = useState(String(Math.round(current)));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const amount = Number(value.replace(/[^0-9.]/g, ''));
  const valid = value.trim() !== '' && Number.isFinite(amount) && amount >= 0 && amount <= MAX_KEEP;

  async function save() {
    if (!valid) return setError(`Pick an amount from $0 to ${money(MAX_KEEP, 0)}.`);
    setSaving(true);
    setError(null);
    try {
      const me = await api.setSafeFloor(Math.round(amount * 100) / 100);
      setStore({ prefsVersion: store.prefsVersion + 1 }); // Today, Family and the chart re-fetch
      onSaved(me.safe_floor);
    } catch (e) {
      const m = e instanceof Error ? e.message : '';
      setError(m.match(/"detail":"([^"]+)"/)?.[1] ?? 'Couldn’t save that. Please try again.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <View style={s.editor}>
      <Text style={s.sheetTitle}>Money I keep in checking</Text>
      <Text style={s.sheetLead}>Runway warns you, and family can step in, before your balance goes under this. It’s yours to choose — some people want $0, others $1,000.</Text>
      <View style={s.presets}>
        {PRESETS.map((n) => {
          const on = amount === n && valid;
          return (
            <PressableScale key={n} onPress={() => { setValue(String(n)); setError(null); }} accessibilityRole="button"
              accessibilityState={{ selected: on }} style={[s.preset, on && s.presetOn]}>
              <Text style={[s.presetText, on && { color: '#111' }]}>{money(n, 0)}</Text>
            </PressableScale>
          );
        })}
      </View>
      <View style={s.inputRow}>
        <Text style={s.dollar}>$</Text>
        <TextInput value={value} onChangeText={(t) => { setValue(t); setError(null); }} keyboardType="decimal-pad"
          inputMode="decimal" accessibilityLabel="Amount to keep, in dollars" style={s.input}
          onSubmitEditing={save} returnKeyType="done" maxLength={7} />
      </View>
      {error && <Text style={[s.whoSub, { color: C.red, marginTop: 6 }]} accessibilityLiveRegion="polite">{error}</Text>}
      <View style={s.editorBtns}>
        <PressableScale onPress={onCancel} accessibilityRole="button" style={[s.btn, s.btnGhost]}>
          <Text style={[s.presetText, { color: C.text2 }]}>Cancel</Text>
        </PressableScale>
        <PressableScale onPress={save} disabled={saving} accessibilityRole="button" style={[s.btn, s.btnSave, (saving || !valid) && { opacity: 0.6 }]}>
          <Text style={[s.presetText, { color: '#111' }]}>{saving ? 'Saving…' : 'Save'}</Text>
        </PressableScale>
      </View>
    </View>
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
  editor: { gap: 4 },
  sheetTitle: { fontFamily: F.bodySemi, fontSize: 20, color: C.text },
  sheetLead: { fontFamily: F.body, fontSize: 15, lineHeight: 21, color: C.text2, marginTop: 2 },
  presets: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 14 },
  preset: { height: 38, paddingHorizontal: 16, borderRadius: 999, borderWidth: 1, borderColor: C.line, justifyContent: 'center' },
  presetOn: { backgroundColor: '#fff', borderColor: '#fff' },
  presetText: { fontFamily: F.bodySemi, fontSize: 14, color: C.text },
  inputRow: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 10, height: 42, paddingHorizontal: 12, borderRadius: 12, borderWidth: 1, borderColor: C.line },
  dollar: { fontFamily: F.bodySemi, fontSize: 16, color: C.text2 },
  input: { flex: 1, fontFamily: F.bodySemi, fontSize: 16, color: C.text, ...(Platform.OS === 'web' ? { outlineStyle: 'none' } : {}) } as object,
  editorBtns: { flexDirection: 'row', gap: 8, marginTop: 12 },
  btn: { flex: 1, height: 48, borderRadius: 999, alignItems: 'center', justifyContent: 'center' },
  btnGhost: { borderWidth: 1, borderColor: C.line },
  btnSave: { backgroundColor: '#fff' },
});

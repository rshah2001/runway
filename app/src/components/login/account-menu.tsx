/**
 * "Hi, Maya ⌄" — who you are, and the way out. Tapping it opens a small menu that grows from the
 * button (name, how you signed in, the money you keep, Sign out); any tap outside or Escape closes it.
 * "Money I keep" is the cushion every "am I okay?" is measured against — the forecast line, dips,
 * spare money, and when family steps in. People differ (one is anxious under $100, another under
 * $1,000), so each person sets their own; nobody can set it for someone else.
 * "Alerts only" swaps Today's numbers for one calm sentence that speaks up only before a dip (for
 * people who avoid looking at their balance — see components/today/quiet-today.tsx).
 * "Appearance" picks Light, Dark, or Auto (follow the device) — see lib/theme.ts.
 * It replaces the plain "Maya · Sign out" chip (account-button.tsx) at the top of Today and on desktop.
 * Looking around as a demo customer (guest), the button reads "Maya · Demo" and the menu keeps only
 * what a look-only visitor can use: appearance, and the way back to switch person or sign in.
 */
import { type ComponentRef, type ElementRef, useEffect, useRef, useState } from 'react';
import { Dimensions, Modal, Platform, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import Svg, { Path } from 'react-native-svg';

import { Sheet } from '@/components/rw/sheet';
import { MenuGrow } from '@/components/rw/menu-grow';
import { PressableScale } from '@/components/rw/ui';
import { C, F } from '@/constants/runway';
import { leave } from '@/lib/account';
import { signedInWithMfa } from '@/lib/auth';
import { api } from '@/lib/api';
import { money } from '@/lib/format';
import { moneyMoved, setStore } from '@/lib/store';
import { useSession } from '@/lib/session';
import { type Appearance, setAppearance, useAppearance } from '@/lib/theme';
import { zoom } from '@/lib/zoom';


export function AccountMenu() {
  const session = useSession();
  // the badge only appears when this sign-in really used a second factor (Auth0's amr claim)
  const [mfa, setMfa] = useState(false);
  useEffect(() => {
    if (session.mode === 'signed-in') signedInWithMfa().then(setMfa).catch(() => setMfa(false));
  }, [session.mode]);
  const button = useRef<ComponentRef<typeof View>>(null);
  const [at, setAt] = useState<{ top: number; right: number } | null>(null);
  const [leaving, setLeaving] = useState(false);
  const [keep, setKeep] = useState<number | null>(null); // what you keep, read when the menu opens
  const [editing, setEditing] = useState(false); // the "Money I keep" sheet
  const [quiet, setQuiet] = useState<boolean | null>(null); // alerts only, read when the menu opens
  const [savingQuiet, setSavingQuiet] = useState(false);
  const [aiActs, setAiActs] = useState<boolean | null>(null); // may Ask Runway set things up?
  const [savingAi, setSavingAi] = useState(false);
  if (session.mode !== 'signed-in' && session.mode !== 'guest') return null;
  const guest = session.mode === 'guest';
  const name = session.name ?? 'there';

  function open() {
    // place the menu under the button, right edges lined up
    // measured in on-screen pixels; the menu is placed in layout pixels (they differ on the scaled desktop site)
    button.current?.measureInWindow((x, y, w, h) => {
      const k = zoom(), vw = Dimensions.get('window').width;
      setAt({ top: (y + h) / k + 8, right: Math.max(8, (vw - (x + w)) / k) });
    });
    if (guest) return; // a guest can't change these, so the menu doesn't offer them
    // only a real number counts: an older server (or a failed read) shows "…", never a guess
    api.me().then((m) => {
      setKeep(typeof m.safe_floor === 'number' ? m.safe_floor : null);
      setQuiet(typeof m.alerts_only === 'boolean' ? m.alerts_only : null); // older server: no switch
      setAiActs(typeof m.ai_actions === 'boolean' ? m.ai_actions : null);
    }).catch(() => { setKeep(null); setQuiet(null); setAiActs(null); });
  }

  async function toggleQuiet() {
    if (quiet === null) return;
    setSavingQuiet(true);
    try {
      const m = await api.setPreferences({ alerts_only: !quiet });
      setQuiet(!!m.alerts_only);
      setStore({ peek: false }); // a fresh choice: show exactly what was chosen
      moneyMoved(); // Today re-reads /me and switches view
    } catch {
      // the switch stays where it was; nothing changed on the server
    } finally {
      setSavingQuiet(false);
    }
  }

  async function toggleAi() {
    if (aiActs === null) return;
    setSavingAi(true);
    try {
      const m = await api.setPreferences({ ai_actions: !aiActs });
      setAiActs(!!m.ai_actions);
    } catch {
      // the switch stays where it was; nothing changed on the server
    } finally {
      setSavingAi(false);
    }
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
        <PressableScale onPress={open} accessibilityRole="button" accessibilityLabel={guest ? `Looking around as ${name}, a demo customer. Menu` : `Signed in as ${name}. Account menu`}
          accessibilityState={{ expanded: !!at }} style={s.hi}>
          <Text style={s.hiText}>{guest ? `${name} · Demo` : `Hi, ${name}`}</Text>
          <Svg width={12} height={12} viewBox="0 0 24 24" fill="none" stroke={C.text} strokeWidth={3} strokeLinecap="round" strokeLinejoin="round"
            style={at ? { transform: [{ rotate: '180deg' }] } : undefined}>
            <Path d="m6 9 6 6 6-6" />
          </Svg>
        </PressableScale>
      </View>
      <Modal transparent visible={!!at} onRequestClose={close} animationType="none">
        <Pressable style={StyleSheet.absoluteFill} onPress={close} accessibilityLabel="Close menu" />
        {at && (
          <MenuGrow style={[s.menu, { top: at.top, right: at.right }]}>
            <View style={s.who}>
              <Text style={s.whoName}>{name}</Text>
              <Text style={s.whoSub}>{guest ? 'Demo customer · look only. Sign in to move money.' : 'Signed in with Auth0'}</Text>
              {mfa && (
                <View style={s.guard} accessibilityLabel="Protected by Auth0 Guardian: this sign-in used a second factor">
                  <Svg width={13} height={13} viewBox="0 0 24 24" fill="none" stroke={C.green} strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round">
                    <Path d="M12 3 4.5 6v5.5c0 4.6 3.2 8.4 7.5 9.5 4.3-1.1 7.5-4.9 7.5-9.5V6L12 3z" />
                    <Path d="m8.8 12.2 2.2 2.2 4.2-4.4" />
                  </Svg>
                  <Text style={s.guardText}>Protected by Auth0 Guardian</Text>
                </View>
              )}
            </View>
            {!guest && (
              <Pressable onPress={() => { close(); setEditing(true); }} disabled={keep === null} accessibilityRole="menuitem"
                accessibilityLabel={`Money I keep in checking: ${keep === null ? 'loading' : money(keep, 0)}. Change`}
                style={({ pressed, hovered }: { pressed: boolean; hovered?: boolean }) => [s.item, (pressed || hovered) && { backgroundColor: C.hover }]}>
                <View style={{ flex: 1 }}>
                  <Text style={[s.itemText, { color: C.text }]}>Money I keep</Text>
                  <Text style={s.whoSub}>Runway warns you before you go under it</Text>
                </View>
                <Text style={[s.itemText, { color: C.text2 }]}>{keep === null ? '…' : money(keep, 0)}</Text>
              </Pressable>
            )}
            {quiet !== null && (
              <Pressable onPress={toggleQuiet} disabled={savingQuiet} accessibilityRole="switch" accessibilityState={{ checked: quiet }}
                accessibilityLabel="Alerts only: hide my numbers and only tell me before a dip"
                style={({ pressed, hovered }: { pressed: boolean; hovered?: boolean }) => [s.item, (pressed || hovered) && { backgroundColor: C.hover }]}>
                <View style={{ flex: 1 }}>
                  <Text style={[s.itemText, { color: C.text }]}>Alerts only</Text>
                  <Text style={s.whoSub}>Hide the numbers, tell me before a dip</Text>
                </View>
                <View style={[s.track, quiet && s.trackOn, savingQuiet && { opacity: 0.6 }]}>
                  <View style={[s.knob, quiet && s.knobOn]} />
                </View>
              </Pressable>
            )}
            {aiActs !== null && (
              <Pressable onPress={toggleAi} disabled={savingAi} accessibilityRole="switch" accessibilityState={{ checked: aiActs }}
                accessibilityLabel="Let Ask Runway set things up for me: money, circles and invites, each one approved by me"
                style={({ pressed, hovered }: { pressed: boolean; hovered?: boolean }) => [s.item, (pressed || hovered) && { backgroundColor: C.hover }]}>
                <View style={{ flex: 1 }}>
                  <Text style={[s.itemText, { color: C.text }]}>Let Ask Runway set things up</Text>
                  <Text style={s.whoSub}>Money, circles, invites — you approve each one</Text>
                </View>
                <View style={[s.track, aiActs && s.trackOn, savingAi && { opacity: 0.6 }]}>
                  <View style={[s.knob, aiActs && s.knobOn]} />
                </View>
              </Pressable>
            )}
            <AppearancePicker />
            <Pressable onPress={signOut} disabled={leaving} accessibilityRole="menuitem"
              style={({ pressed, hovered }: { pressed: boolean; hovered?: boolean }) => [s.item, (pressed || hovered) && { backgroundColor: C.hover }]}>
              <Svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke={C.red} strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round">
                <Path d="M15 4h4v16h-4M10 8l-4 4 4 4M6 12h10" />
              </Svg>
              <Text style={s.itemText}>{guest ? 'Switch person or sign in' : leaving ? 'Signing out…' : 'Sign out'}</Text>
            </Pressable>
          </MenuGrow>
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

const LOOKS: { key: Appearance; label: string; icon: string }[] = [
  { key: 'system', label: 'Auto', icon: 'M4 5h16v11H4zM9 20h6M12 16v4' },
  { key: 'light', label: 'Light', icon: 'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4' },
  { key: 'dark', label: 'Dark', icon: 'M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z' },
];

/** Auto · Light · Dark. It changes the page at once (the menu included), so you see what you picked. */
function AppearancePicker() {
  const { choice } = useAppearance();
  return (
    <View style={s.look}>
      <Text style={[s.itemText, { color: C.text }]}>Appearance</Text>
      <View style={s.segs} accessibilityRole="radiogroup" accessibilityLabel="Appearance">
        {LOOKS.map(({ key, label, icon }) => {
          const on = choice === key;
          return (
            <Pressable key={key} onPress={() => setAppearance(key)} accessibilityRole="radio" accessibilityState={{ checked: on }}
              accessibilityLabel={key === 'system' ? 'Auto: match this device' : label} style={[s.seg, on && s.segOn]}>
              <Svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke={on ? C.text : C.text2} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                <Path d={icon} />
              </Svg>
              <Text style={[s.segText, on && { color: C.text }]}>{label}</Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

const PRESETS = [0, 50, 100, 200, 300, 500, 1000];
const MAX_KEEP = 5000; // the server's limit too

/** Pick or type what you keep; saves for you only, then every screen re-fetches its forecast. */
function KeepEditor({ current, onSaved, onCancel }: { current: number; onSaved: (v: number) => void; onCancel: () => void }) {
  const [value, setValue] = useState(String(Math.round(current)));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [typing, setTyping] = useState(!PRESETS.includes(Math.round(current))); // "Custom" is the choice
  const input = useRef<ElementRef<typeof TextInput>>(null);
  const amount = Number(value.replace(/[^0-9.]/g, ''));
  const valid = value.trim() !== '' && Number.isFinite(amount) && amount >= 0 && amount <= MAX_KEEP;
  // one thing is selected at a time: a preset, or Custom (your own amount in the box)
  const custom = typing || !PRESETS.includes(amount);

  async function save() {
    if (!valid) return setError(`Pick an amount from $0 to ${money(MAX_KEEP, 0)}.`);
    setSaving(true);
    setError(null);
    try {
      const me = await api.setSafeFloor(Math.round(amount * 100) / 100);
      moneyMoved(); // what you keep changed: Today, Spending, Family and the chart re-fetch
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
          const on = !custom && amount === n;
          return (
            <PressableScale key={n} onPress={() => { setValue(String(n)); setTyping(false); setError(null); }} accessibilityRole="button"
              accessibilityState={{ selected: on }} style={[s.preset, on && s.presetOn]}>
              <Text style={[s.presetText, on && { color: C.onPrimary }]}>{money(n, 0)}</Text>
            </PressableScale>
          );
        })}
        <PressableScale onPress={() => { setTyping(true); setError(null); input.current?.focus(); }} accessibilityRole="button"
          accessibilityState={{ selected: custom }} accessibilityLabel="Custom amount" style={[s.preset, custom && s.presetOn]}>
          <Text style={[s.presetText, custom && { color: C.onPrimary }]}>Custom</Text>
        </PressableScale>
      </View>
      <View style={[s.inputRow, custom && s.inputOn]}>
        <Text style={[s.dollar, custom && { color: C.text }]}>$</Text>
        <TextInput ref={input} value={value} onChangeText={(t) => { setValue(t); setTyping(true); setError(null); }}
          onFocus={() => setTyping(true)} keyboardType="decimal-pad" inputMode="decimal"
          accessibilityLabel="Your own amount to keep, in dollars" placeholder="Your amount" placeholderTextColor={C.text3}
          style={s.input} onSubmitEditing={save} returnKeyType="done" maxLength={7} />
      </View>
      {/* say exactly what Save will do, so a highlighted preset is never mistaken for the choice */}
      <Text style={[s.whoSub, { marginTop: 8 }]} accessibilityLiveRegion="polite">
        {valid ? `You’ll keep ${money(amount, 0)} in checking.` : `Type an amount from $0 to ${money(MAX_KEEP, 0)}.`}
      </Text>
      {error && <Text style={[s.whoSub, { color: C.red, marginTop: 6 }]} accessibilityLiveRegion="polite">{error}</Text>}
      <View style={s.editorBtns}>
        <PressableScale onPress={onCancel} accessibilityRole="button" style={[s.btn, s.btnGhost]}>
          <Text style={[s.presetText, { color: C.text2 }]}>Cancel</Text>
        </PressableScale>
        <PressableScale onPress={save} disabled={saving} accessibilityRole="button" style={[s.btn, s.btnSave, (saving || !valid) && { opacity: 0.6 }]}>
          <Text style={[s.presetText, { color: C.onPrimary }]}>{saving ? 'Saving…' : 'Save'}</Text>
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
  guard: { flexDirection: 'row', alignItems: 'center', gap: 5, marginTop: 6, alignSelf: 'flex-start', paddingHorizontal: 8, height: 22, borderRadius: 11, backgroundColor: 'rgba(74,222,128,0.12)' },
  guardText: { fontFamily: F.bodySemi, fontSize: 12, color: C.green },
  item: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingHorizontal: 12, paddingVertical: 11, borderRadius: 12, borderTopWidth: 1, borderTopColor: C.line },
  track: { width: 44, height: 26, borderRadius: 13, backgroundColor: C.line, padding: 3 },
  trackOn: { backgroundColor: C.green },
  knob: { width: 20, height: 20, borderRadius: 10, backgroundColor: '#fff' },
  knobOn: { transform: [{ translateX: 18 }] },
  itemText: { fontFamily: F.bodySemi, fontSize: 15, color: C.red },
  look: { paddingHorizontal: 12, paddingTop: 11, paddingBottom: 12, borderTopWidth: 1, borderTopColor: C.line, gap: 9 },
  segs: { flexDirection: 'row', padding: 3, borderRadius: 12, backgroundColor: C.bg, gap: 3 },
  seg: { flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 5, height: 32, borderRadius: 9 },
  segOn: { backgroundColor: C.card, shadowColor: '#000', shadowOpacity: 0.18, shadowRadius: 4, shadowOffset: { width: 0, height: 1 } },
  segText: { fontFamily: F.bodySemi, fontSize: 13, color: C.text2 },
  editor: { gap: 4 },
  sheetTitle: { fontFamily: F.bodySemi, fontSize: 20, color: C.text },
  sheetLead: { fontFamily: F.body, fontSize: 15, lineHeight: 21, color: C.text2, marginTop: 2 },
  presets: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 14 },
  preset: { height: 38, paddingHorizontal: 16, borderRadius: 999, borderWidth: 1, borderColor: C.line, justifyContent: 'center' },
  presetOn: { backgroundColor: C.primary, borderColor: C.primary },
  presetText: { fontFamily: F.bodySemi, fontSize: 14, color: C.text },
  inputRow: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 10, height: 42, paddingHorizontal: 12, borderRadius: 12, borderWidth: 1, borderColor: C.line },
  dollar: { fontFamily: F.bodySemi, fontSize: 16, color: C.text2 },
  inputOn: { borderColor: C.text, borderWidth: 1.5 }, // Custom is the choice: the box is what Save uses
  input: { flex: 1, fontFamily: F.bodySemi, fontSize: 16, color: C.text, ...(Platform.OS === 'web' ? { outlineStyle: 'none' } : {}) } as object,
  editorBtns: { flexDirection: 'row', gap: 8, marginTop: 12 },
  btn: { flex: 1, height: 48, borderRadius: 999, alignItems: 'center', justifyContent: 'center' },
  btnGhost: { borderWidth: 1, borderColor: C.line },
  btnSave: { backgroundColor: C.primary },
});

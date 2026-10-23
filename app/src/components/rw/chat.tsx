/**
 * Runway's chat, opened from the round button in the phone bottom bar or the corner button on desktop.
 * Desktop: a chat window anchored to the bottom-right corner. Phones: a sheet that rises most of the
 * way up over the dimmed page (tap the dim area or the handle to close), so you keep your place.
 * The conversation lives as long as the app, so closing and reopening keeps it.
 * Under the title: whose Gemini key answers — Runway's, or the visitor's own (lib/gemini-key.ts).
 *
 * Motion: opening is occasional → standard animation, off the JS thread.
 *  - desktop window: scale 0.96 → 1 + fade from its corner, 200ms ease-out (closes in 150ms)
 *  - phone sheet: slides up from the bottom, 320ms iOS sheet curve (closes in 240ms); the page dims behind
 *  - reduced motion: fades only.
 */
import { useRouter } from 'expo-router';
import { type ComponentRef, type PropsWithChildren, useEffect, useRef, useState } from 'react';
import {
  BackHandler,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  useWindowDimensions,
  View,
} from 'react-native';
import Animated, { Easing, useAnimatedStyle, useReducedMotion, useSharedValue, withTiming } from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Svg, { Path } from 'react-native-svg';

import { C, F } from '@/constants/runway';
import { api } from '@/lib/api';
import { looksLikeKey, setGeminiKey, useGeminiKey } from '@/lib/gemini-key';
import { zoom } from '@/lib/zoom';
import { useSession } from '@/lib/session';
import { setStore, useStore } from '@/lib/store';
import type { PendingAction } from '@/lib/types';

import { ApprovalCard } from './approval-card';
import { Icon } from './icons';
import { Caps, PressableScale, T, useWide } from './ui';

type Msg =
  | { id: number; kind: 'text'; from: 'me' | 'bot'; text: string; tools?: string[]; ownKey?: boolean }
  | { id: number; kind: 'approval'; action: PendingAction }
  | { id: number; kind: 'error'; text: string };

const TOOL_NAME: Record<string, string> = {
  get_forecast: 'forecast', simulate_purchase: 'purchase simulator', find_recurring: 'recurring charges',
  propose_transfer: 'transfer proposal', reschedule_bill: 'bill scheduler',
};
const CHIPS = ['Can I afford $180 on Friday?', 'Fix it', 'What subscriptions do I have?'];
const MAX_LEN = 500;
const EASE_OUT = Easing.bezier(0.23, 1, 0.32, 1);
const EASE_SHEET = Easing.bezier(0.32, 0.72, 0, 1);
let nextId = 1;

export const openChat = () => setStore({ chatOpen: true });
const closeChat = () => setStore({ chatOpen: false });

/** Floating button + the chat surface. Mounted once in the root layout, above the tabs. */
export function ChatLauncher() {
  const wide = useWide();
  const reduced = useReducedMotion();
  const height = useWindowDimensions().height / zoom(); // layout px on the scaled desktop site
  const { chatOpen } = useStore();
  const p = useSharedValue(0); // 0 closed … 1 open
  const [mounted, setMounted] = useState(false); // panel stays mounted after first open, so the chat survives

  if (chatOpen && !mounted) setMounted(true);

  useEffect(() => {
    const dur = chatOpen ? (wide ? 200 : 320) : wide ? 150 : 240;
    p.set(withTiming(chatOpen ? 1 : 0, { duration: dur, easing: wide ? EASE_OUT : EASE_SHEET }));
  }, [chatOpen, wide, p]);

  // Android back button and the Escape key close the chat.
  useEffect(() => {
    if (!chatOpen) return;
    const sub = BackHandler.addEventListener('hardwareBackPress', () => (closeChat(), true));
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && closeChat();
    if (Platform.OS === 'web') window.addEventListener('keydown', onKey);
    return () => {
      sub.remove();
      if (Platform.OS === 'web') window.removeEventListener('keydown', onKey);
    };
  }, [chatOpen]);

  const panelStyle = useAnimatedStyle(() => {
    const v = p.get();
    if (reduced) return { opacity: v };
    return wide
      ? { opacity: v, transform: [{ translateY: (1 - v) * 8 }, { scale: 0.96 + v * 0.04 }] }
      : { opacity: 1, transform: [{ translateY: (1 - v) * height }] };
  });
  const fabStyle = useAnimatedStyle(() => ({ opacity: 1 }));
  const scrimStyle = useAnimatedStyle(() => ({ opacity: p.get() * 0.55 }));

  const fabBottom = 28; // desktop corner (phones use the bottom-bar button)

  return (
    <View style={StyleSheet.absoluteFill} pointerEvents="box-none">
      {mounted && !wide && (
        <Animated.View pointerEvents={chatOpen ? 'auto' : 'none'} style={[StyleSheet.absoluteFill, s.scrim, scrimStyle]}>
          <Pressable style={StyleSheet.absoluteFill} onPress={closeChat} accessibilityRole="button" accessibilityLabel="Close chat" />
        </Animated.View>
      )}
      {mounted && (
        <Animated.View pointerEvents={chatOpen ? 'auto' : 'none'} accessibilityViewIsModal={chatOpen}
          style={[wide ? [s.window, { bottom: fabBottom + 68, maxHeight: Math.min(660, height - 170) }] : [s.sheet, { height: Math.min(height * 0.78, 720) }], panelStyle]}>
          <ChatPanel wide={wide} />
        </Animated.View>
      )}
      {/* Desktop only: on phones the chat button sits in the bottom bar (components/app-tabs.tsx). */}
      {wide && <Animated.View style={[s.fabWrap, { bottom: fabBottom, right: 32 }, fabStyle]} pointerEvents="box-none">
        <PressableScale onPress={() => setStore({ chatOpen: !chatOpen })} style={s.fab} accessibilityRole="button"
          accessibilityLabel={chatOpen ? 'Close chat' : 'Ask Runway'}>
          {chatOpen ? <Icon name="close" size={22} color={C.onPrimary} /> : (
            <Svg width={24} height={24} viewBox="0 0 24 24" fill="none" stroke={C.onPrimary} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
              <Path d="M4 5.5h16v10H9l-5 3.5z" /><Path d="M8 10.5h8" />
            </Svg>
          )}
        </PressableScale>
      </Animated.View>}
    </View>
  );
}

/** The conversation itself: header, thread, suggestion chips, composer. */
function ChatPanel({ wide }: { wide: boolean }) {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const reduced = useReducedMotion();
  const scroll = useRef<ComponentRef<typeof ScrollView>>(null);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const name = useSession().name;
  const [msgs, setMsgs] = useState<Msg[]>([
    { id: nextId++, kind: 'text', from: 'bot', text: `Hi ${name ?? 'there'}. Ask whether you can afford something, or say "Fix it" and I'll suggest a transfer you can approve.` },
  ]);

  async function send(raw: string) {
    const message = raw.trim().slice(0, MAX_LEN);
    if (!message || busy) return;
    setText('');
    setBusy(true);
    setMsgs((m) => [...m, { id: nextId++, kind: 'text', from: 'me', text: message }]);
    try {
      const r = await api.chat(message);
      setMsgs((m) => [
        ...m,
        // their key didn't answer: say so, rather than let a rule-based reply pass for Gemini's
        ...(r.own_key === 'failed'
          ? [{ id: nextId++, kind: 'error' as const, text: `${r.own_key_problem ?? 'Your Gemini key didn’t answer.'} This reply came from Runway’s built-in rules.` }]
          : []),
        { id: nextId++, kind: 'text', from: 'bot', text: r.reply, tools: r.tool_calls, ownKey: r.own_key === 'used' },
        ...(r.pending_action ? [{ id: nextId++, kind: 'approval' as const, action: r.pending_action }] : []),
      ]);
    } catch {
      setMsgs((m) => [...m, { id: nextId++, kind: 'error', text: "Couldn't reach Runway. Check your connection and try again." }]);
    } finally {
      setBusy(false);
    }
  }

  const top = wide ? 14 : 0;
  const bottom = wide ? 12 : Math.max(12, insets.bottom);

  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      {!wide && (
        <Pressable onPress={closeChat} style={s.grabHit} accessibilityRole="button" accessibilityLabel="Close chat">
          <View style={s.grab} />
        </Pressable>
      )}
      <View style={[s.head, { paddingTop: top }, !wide && s.headSheet]}>
        <View style={{ flex: 1 }}>
          <Text style={[s.title, wide && { fontSize: 20 }]}>Ask Runway</Text>
          <T tone="dim" style={{ fontSize: 14, marginTop: 2 }}>Every number comes from your forecast, never guessed.</T>
          <OwnKey />
        </View>
      </View>
      <ScrollView ref={scroll} style={{ flex: 1 }} contentContainerStyle={[s.thread, !wide && { justifyContent: 'flex-start' }]} keyboardShouldPersistTaps="handled"
        onContentSizeChange={() => scroll.current?.scrollToEnd({ animated: !reduced })}>
        {msgs.map((m) => (
          <MsgIn key={m.id} stretch={m.kind === 'approval'}>
            {m.kind === 'text' && (
              <View style={{ alignItems: m.from === 'me' ? 'flex-end' : 'flex-start' }}>
                <View style={[s.msg, m.from === 'me' ? s.me : s.bot]}>
                  <T style={[s.msgText, m.from === 'me' && { color: C.onPrimary }]}>{m.text}</T>
                </View>
                {m.ownKey && <Caps tone="faint" size={11} style={s.ownTag}>Answered with your Gemini key</Caps>}
                {m.tools?.length ? (
                  <View style={s.tools}>
                    <Icon name="tool" size={12} color={C.text3} />
                    <Caps tone="faint" size={11}>Used: {m.tools.map((t) => TOOL_NAME[t] ?? t).join(', ')}</Caps>
                  </View>
                ) : null}
              </View>
            )}
            {m.kind === 'approval' && <ApprovalCard action={m.action} onViewRunway={() => { closeChat(); router.navigate('/'); }} />}
            {m.kind === 'error' && <View style={[s.msg, s.bot, { borderWidth: 1, borderColor: C.red }]}><T tone="red">{m.text}</T></View>}
          </MsgIn>
        ))}
        {busy && <View style={[s.msg, s.bot, { alignSelf: 'flex-start' }]} accessibilityLabel="Runway is thinking"><T tone="dim">Thinking…</T></View>}
      </ScrollView>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chips} style={{ flexGrow: 0 }} keyboardShouldPersistTaps="handled">
        {CHIPS.map((c) => (
          <PressableScale key={c} onPress={() => send(c)} disabled={busy} style={s.chip} accessibilityRole="button">
            <T style={{ fontSize: 14 }}>{c}</T>
          </PressableScale>
        ))}
      </ScrollView>
      <View style={[s.composer, { paddingBottom: bottom }]}>
        <TextInput value={text} onChangeText={setText} placeholder="Ask about your money" placeholderTextColor={C.text3}
          style={s.input} maxLength={MAX_LEN} returnKeyType="send" onSubmitEditing={() => send(text)} editable={!busy}
          accessibilityLabel="Message" />
        <PressableScale onPress={() => send(text)} disabled={!text.trim() || busy} accessibilityRole="button" accessibilityLabel="Send"
          style={[s.send, (!text.trim() || busy) && { opacity: 0.35 }]}>
          <Icon name="send" size={18} color={C.onPrimary} />
        </PressableScale>
      </View>
    </KeyboardAvoidingView>
  );
}

/**
 * "Gemini: Runway's key · Use your own" → a field for the visitor's own key. Set, it reads
 * "Gemini: your key ••••wxyz · Remove". The key stays in this tab and goes only with chat messages.
 */
function OwnKey() {
  const own = useGeminiKey();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const ok = looksLikeKey(draft.trim());

  if (own) {
    return (
      <View style={s.keyRow}>
        <T tone="dim" style={s.keyText}>Gemini: your key ••••{own.slice(-4)}</T>
        <Pressable onPress={() => setGeminiKey(null)} accessibilityRole="button" accessibilityLabel="Stop using my Gemini key">
          <T style={[s.keyText, s.keyLink]}>Remove</T>
        </Pressable>
      </View>
    );
  }
  if (!editing) {
    return (
      <View style={s.keyRow}>
        <T tone="dim" style={s.keyText}>Gemini: Runway’s key</T>
        <Pressable onPress={() => setEditing(true)} accessibilityRole="button" accessibilityLabel="Use my own Gemini API key">
          <T style={[s.keyText, s.keyLink]}>Use your own</T>
        </Pressable>
      </View>
    );
  }
  function save() {
    if (!ok) return;
    setGeminiKey(draft.trim());
    setDraft('');
    setEditing(false);
  }
  return (
    <View style={{ gap: 6, marginTop: 8 }}>
      <View style={s.keyRow}>
        <TextInput value={draft} onChangeText={setDraft} placeholder="Paste your Gemini API key" placeholderTextColor={C.text3}
          secureTextEntry autoCapitalize="none" autoCorrect={false} autoComplete="off" onSubmitEditing={save}
          style={[s.input, s.keyInput]} accessibilityLabel="Your Gemini API key" />
        <PressableScale onPress={save} disabled={!ok} accessibilityRole="button" style={[s.keySave, !ok && { opacity: 0.35 }]}>
          <Text style={s.keySaveText}>Use</Text>
        </PressableScale>
        <Pressable onPress={() => { setDraft(''); setEditing(false); }} accessibilityRole="button">
          <T tone="dim" style={s.keyText}>Cancel</T>
        </Pressable>
      </View>
      <T tone="faint" style={s.keyNote}>
        Kept in this tab only and sent only with your chat messages. Runway never stores it. Get a free key at aistudio.google.com/apikey.
      </T>
    </View>
  );
}

/** A new message fades up 6px over 220ms (ease-out). Reduced motion: fade only. */
function MsgIn({ children, stretch }: PropsWithChildren<{ stretch?: boolean }>) {
  const reduced = useReducedMotion();
  const v = useSharedValue(0);
  useEffect(() => {
    v.set(withTiming(1, { duration: 220, easing: EASE_OUT }));
  }, [v]);
  const style = useAnimatedStyle(() => ({ opacity: v.get(), transform: [{ translateY: reduced ? 0 : (1 - v.get()) * 6 }] }));
  return <Animated.View style={[stretch && { alignSelf: 'stretch' }, style]}>{children}</Animated.View>;
}

const s = StyleSheet.create({
  window: { position: 'absolute', right: 32, width: 400, height: 620, borderRadius: 18, overflow: 'hidden', backgroundColor: C.bg,
    borderWidth: 1, borderColor: C.line, transformOrigin: 'bottom right',
    shadowColor: '#000', shadowOpacity: 0.45, shadowRadius: 30, shadowOffset: { width: 0, height: 16 }, elevation: 16 },
  scrim: { backgroundColor: '#000', zIndex: 19 },
  sheet: { position: 'absolute', left: 0, right: 0, bottom: 0, backgroundColor: C.card, zIndex: 20,
    borderTopLeftRadius: 28, borderTopRightRadius: 28, overflow: 'hidden',
    shadowColor: '#000', shadowOpacity: 0.4, shadowRadius: 30, shadowOffset: { width: 0, height: -8 }, elevation: 24 },
  grabHit: { alignSelf: 'center', paddingTop: 10, paddingBottom: 10, paddingHorizontal: 30 },
  grab: { width: 38, height: 5, borderRadius: 3, backgroundColor: C.grab },
  headSheet: { borderBottomWidth: 0, paddingHorizontal: 20 },
  title: { fontFamily: F.bodySemi, fontSize: 22, color: C.text, letterSpacing: -0.2 },
  head: { flexDirection: 'row', alignItems: 'flex-start', gap: 12, paddingHorizontal: 14, paddingBottom: 10, borderBottomWidth: 1, borderBottomColor: C.line },
  thread: { gap: 10, paddingVertical: 14, paddingHorizontal: 12, flexGrow: 1, justifyContent: 'flex-end' },
  msg: { maxWidth: '88%', paddingVertical: 11, paddingHorizontal: 14, borderRadius: 14 },
  bot: { backgroundColor: C.card2, borderTopLeftRadius: 4 },
  me: { backgroundColor: C.primary, borderTopRightRadius: 4 },
  msgText: { fontSize: 16, lineHeight: 22 },
  tools: { flexDirection: 'row', alignItems: 'center', gap: 5, marginTop: 4, marginLeft: 6 },
  chips: { gap: 8, paddingHorizontal: 12, paddingBottom: 10 },
  chip: { height: 38, paddingHorizontal: 14, borderRadius: 999, backgroundColor: C.card2, justifyContent: 'center' },
  composer: { flexDirection: 'row', gap: 8, alignItems: 'center', paddingHorizontal: 12 },
  input: { flex: 1, height: 46, paddingHorizontal: 16, borderRadius: 999, backgroundColor: C.card2, borderWidth: 1, borderColor: C.line2,
    color: C.text, fontFamily: F.body, fontSize: 16 },
  send: { width: 46, height: 46, borderRadius: 23, backgroundColor: C.primary, alignItems: 'center', justifyContent: 'center' },
  ownTag: { marginTop: 4, marginLeft: 6 },
  keyRow: { flexDirection: 'row', alignItems: 'center', gap: 10, marginTop: 6, flexWrap: 'wrap' },
  keyText: { fontSize: 13 },
  keyLink: { color: C.primary, fontFamily: F.bodySemi },
  keyInput: { flex: 1, minWidth: 160, height: 38, fontSize: 14 },
  keySave: { height: 38, paddingHorizontal: 16, borderRadius: 999, backgroundColor: C.primary, alignItems: 'center', justifyContent: 'center' },
  keySaveText: { fontFamily: F.bodySemi, fontSize: 14, color: C.onPrimary },
  keyNote: { fontSize: 12, lineHeight: 17 },
  fabWrap: { position: 'absolute', zIndex: 30 },
  fab: { width: 58, height: 58, borderRadius: 29, backgroundColor: C.primary, alignItems: 'center', justifyContent: 'center',
    shadowColor: '#000', shadowOpacity: 0.35, shadowRadius: 16, shadowOffset: { width: 0, height: 8 }, elevation: 10 },
});

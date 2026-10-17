/**
 * Runway's chat, opened from the round button in the phone bottom bar or the corner button on desktop.
 * Desktop: a chat window anchored to the bottom-right corner. Phones: a full-screen sheet.
 * The conversation lives as long as the app, so closing and reopening keeps it.
 *
 * Motion: opening is occasional → standard animation, off the JS thread.
 *  - desktop window: scale 0.96 → 1 + fade from its corner, 200ms ease-out (closes in 150ms)
 *  - phone sheet: slides up from the bottom, 320ms iOS sheet curve (closes in 240ms)
 *  - reduced motion: fades only.
 */
import { useRouter } from 'expo-router';
import { type ComponentRef, type PropsWithChildren, useEffect, useRef, useState } from 'react';
import {
  BackHandler,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  StyleSheet,
  TextInput,
  useWindowDimensions,
  View,
} from 'react-native';
import Animated, { Easing, useAnimatedStyle, useReducedMotion, useSharedValue, withTiming } from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Svg, { Path } from 'react-native-svg';

import { C, F } from '@/constants/runway';
import { api } from '@/lib/api';
import { setStore, useStore } from '@/lib/store';
import type { PendingAction } from '@/lib/types';

import { ApprovalCard } from './approval-card';
import { Icon } from './icons';
import { Caps, PressableScale, T, useWide } from './ui';

type Msg =
  | { id: number; kind: 'text'; from: 'me' | 'bot'; text: string; tools?: string[] }
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
  const { height } = useWindowDimensions();
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

  const fabBottom = 28; // desktop corner (phones use the bottom-bar button)

  return (
    <View style={StyleSheet.absoluteFill} pointerEvents="box-none">
      {mounted && (
        <Animated.View pointerEvents={chatOpen ? 'auto' : 'none'} accessibilityViewIsModal={chatOpen}
          style={[wide ? [s.window, { bottom: fabBottom + 68, maxHeight: Math.min(680, height - 140) }] : s.sheet, panelStyle]}>
          <ChatPanel wide={wide} />
        </Animated.View>
      )}
      {/* Desktop only: on phones the chat button sits in the bottom bar (components/app-tabs.tsx). */}
      {wide && <Animated.View style={[s.fabWrap, { bottom: fabBottom, right: 32 }, fabStyle]} pointerEvents="box-none">
        <PressableScale onPress={() => setStore({ chatOpen: !chatOpen })} style={s.fab} accessibilityRole="button"
          accessibilityLabel={chatOpen ? 'Close chat' : 'Ask Runway'}>
          {chatOpen ? <Icon name="close" size={22} color="#111" /> : (
            <Svg width={24} height={24} viewBox="0 0 24 24" fill="none" stroke="#111" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
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
  const [msgs, setMsgs] = useState<Msg[]>([
    { id: nextId++, kind: 'text', from: 'bot', text: 'Hi Maya. Ask whether you can afford something, or say "Fix it" and I\'ll suggest a transfer you can approve.' },
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
        { id: nextId++, kind: 'text', from: 'bot', text: r.reply, tools: r.tool_calls },
        ...(r.pending_action ? [{ id: nextId++, kind: 'approval' as const, action: r.pending_action }] : []),
      ]);
    } catch {
      setMsgs((m) => [...m, { id: nextId++, kind: 'error', text: "Couldn't reach Runway. Check your connection and try again." }]);
    } finally {
      setBusy(false);
    }
  }

  const top = wide ? 14 : Platform.OS === 'web' ? 14 : insets.top + 8;
  const bottom = wide ? 12 : Math.max(12, insets.bottom);

  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <View style={[s.head, { paddingTop: top }]}>
        <View style={{ flex: 1 }}>
          <Caps size={wide ? 22 : 28} style={{ textTransform: 'none', letterSpacing: 0.3 }}>Ask Runway</Caps>
          <T tone="dim" style={{ fontSize: 13 }}>Ask anything about your money. Answers use your real numbers.</T>
        </View>
        {!wide && (
          <PressableScale onPress={closeChat} style={s.close} accessibilityRole="button" accessibilityLabel="Close chat">
            <Icon name="close" size={20} color={C.text} />
          </PressableScale>
        )}
      </View>
      <ScrollView ref={scroll} style={{ flex: 1 }} contentContainerStyle={s.thread} keyboardShouldPersistTaps="handled"
        onContentSizeChange={() => scroll.current?.scrollToEnd({ animated: !reduced })}>
        {msgs.map((m) => (
          <MsgIn key={m.id} stretch={m.kind === 'approval'}>
            {m.kind === 'text' && (
              <View style={{ alignItems: m.from === 'me' ? 'flex-end' : 'flex-start' }}>
                <View style={[s.msg, m.from === 'me' ? s.me : s.bot]}>
                  <T style={[s.msgText, m.from === 'me' && { color: '#111' }]}>{m.text}</T>
                </View>
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
          <Icon name="send" size={18} color="#111" />
        </PressableScale>
      </View>
    </KeyboardAvoidingView>
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
  sheet: { ...StyleSheet.absoluteFill, backgroundColor: C.bg, zIndex: 20 },
  head: { flexDirection: 'row', alignItems: 'flex-start', gap: 12, paddingHorizontal: 14, paddingBottom: 10, borderBottomWidth: 1, borderBottomColor: C.line },
  close: { width: 40, height: 40, borderRadius: 20, backgroundColor: C.card2, alignItems: 'center', justifyContent: 'center' },
  thread: { gap: 10, paddingVertical: 14, paddingHorizontal: 12, flexGrow: 1, justifyContent: 'flex-end' },
  msg: { maxWidth: '88%', paddingVertical: 11, paddingHorizontal: 14, borderRadius: 14 },
  bot: { backgroundColor: C.card, borderTopLeftRadius: 4 },
  me: { backgroundColor: '#fff', borderTopRightRadius: 4 },
  msgText: { fontSize: 16, lineHeight: 22 },
  tools: { flexDirection: 'row', alignItems: 'center', gap: 5, marginTop: 4, marginLeft: 6 },
  chips: { gap: 8, paddingHorizontal: 12, paddingBottom: 10 },
  chip: { height: 36, paddingHorizontal: 14, borderRadius: 999, backgroundColor: C.card, borderWidth: 1, borderColor: C.line, justifyContent: 'center' },
  composer: { flexDirection: 'row', gap: 8, alignItems: 'center', paddingHorizontal: 12 },
  input: { flex: 1, height: 46, paddingHorizontal: 16, borderRadius: 999, backgroundColor: C.card, borderWidth: 1, borderColor: C.line,
    color: C.text, fontFamily: F.body, fontSize: 16 },
  send: { width: 46, height: 46, borderRadius: 23, backgroundColor: '#fff', alignItems: 'center', justifyContent: 'center' },
  fabWrap: { position: 'absolute', zIndex: 30 },
  fab: { width: 58, height: 58, borderRadius: 29, backgroundColor: '#fff', alignItems: 'center', justifyContent: 'center',
    shadowColor: '#000', shadowOpacity: 0.35, shadowRadius: 16, shadowOffset: { width: 0, height: 8 }, elevation: 10 },
});

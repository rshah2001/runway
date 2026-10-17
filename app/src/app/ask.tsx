// Ask — owner: an2thu. Chat with Runway's agent (POST /agent/chat). Every reply says which tool
// produced its numbers; money moves only through the approval card.
import { useRouter } from 'expo-router';
import { type ComponentRef, type PropsWithChildren, useEffect, useRef, useState } from 'react';
import { KeyboardAvoidingView, Platform, ScrollView, StyleSheet, TextInput, View } from 'react-native';
import Animated, { Easing, useAnimatedStyle, useReducedMotion, useSharedValue, withTiming } from 'react-native-reanimated';

import { ApprovalCard } from '@/components/rw/approval-card';
import { Icon } from '@/components/rw/icons';
import { Caps, Page, PressableScale, T, useWide } from '@/components/rw/ui';
import { C, F } from '@/constants/runway';
import { api } from '@/lib/api';
import type { PendingAction } from '@/lib/types';

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
let nextId = 1;

export default function AskScreen() {
  const wide = useWide();
  const router = useRouter();
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

  return (
    <Page scroll={false}>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <View style={[s.head, wide && { paddingTop: 8 }]}>
          <Caps size={34} style={{ letterSpacing: 0.4, textTransform: 'none' }}>Ask</Caps>
          <T tone="dim">Answers come from your forecast. Runway never guesses a number.</T>
        </View>
        <ScrollView ref={scroll} style={{ flex: 1 }} contentContainerStyle={s.thread}
          onContentSizeChange={() => scroll.current?.scrollToEnd({ animated: !reduced })}>
          {msgs.map((m) => (
            <MsgIn key={m.id} stretch={m.kind === 'approval'}>
              {m.kind === 'text' && (
                <View style={{ alignItems: m.from === 'me' ? 'flex-end' : 'flex-start' }}>
                  <View style={[s.msg, m.from === 'me' ? s.me : s.bot, wide && { maxWidth: 620 }]}>
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
              {m.kind === 'approval' && <ApprovalCard action={m.action} onViewRunway={() => router.navigate('/')} />}
              {m.kind === 'error' && <View style={[s.msg, s.bot, { borderWidth: 1, borderColor: C.red }]}><T tone="red">{m.text}</T></View>}
            </MsgIn>
          ))}
          {busy && <View style={[s.msg, s.bot, s.typing]} accessibilityLabel="Runway is thinking"><T tone="dim">Thinking…</T></View>}
        </ScrollView>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chips} style={{ flexGrow: 0 }}>
          {CHIPS.map((c) => (
            <PressableScale key={c} onPress={() => send(c)} disabled={busy} style={s.chip} accessibilityRole="button">
              <T style={{ fontSize: 14 }}>{c}</T>
            </PressableScale>
          ))}
        </ScrollView>
        <View style={s.composer}>
          <TextInput value={text} onChangeText={setText} placeholder="Ask about your money" placeholderTextColor={C.text3}
            style={s.input} maxLength={MAX_LEN} returnKeyType="send" onSubmitEditing={() => send(text)} editable={!busy}
            accessibilityLabel="Message" />
          <PressableScale onPress={() => send(text)} disabled={!text.trim() || busy} accessibilityRole="button" accessibilityLabel="Send"
            style={[s.send, (!text.trim() || busy) && { opacity: 0.35 }]}>
            <Icon name="send" size={18} color="#111" />
          </PressableScale>
        </View>
      </KeyboardAvoidingView>
    </Page>
  );
}

/** A new message fades up 6px over 220ms (ease-out) — it explains what just arrived. Reduced motion: fade only. */
function MsgIn({ children, stretch }: PropsWithChildren<{ stretch?: boolean }>) {
  const reduced = useReducedMotion();
  const p = useSharedValue(0);
  useEffect(() => {
    p.set(withTiming(1, { duration: 220, easing: Easing.bezier(0.23, 1, 0.32, 1) }));
  }, [p]);
  const style = useAnimatedStyle(() => ({ opacity: p.get(), transform: [{ translateY: reduced ? 0 : (1 - p.get()) * 6 }] }));
  return <Animated.View style={[stretch && { alignSelf: 'stretch' }, style]}>{children}</Animated.View>;
}

const s = StyleSheet.create({
  head: { paddingHorizontal: 4, paddingBottom: 4 },
  thread: { gap: 10, paddingVertical: 14, paddingHorizontal: 2, flexGrow: 1, justifyContent: 'flex-end' },
  msg: { maxWidth: '86%', paddingVertical: 11, paddingHorizontal: 14, borderRadius: 14 },
  bot: { backgroundColor: C.card, borderTopLeftRadius: 4 },
  me: { backgroundColor: '#fff', borderTopRightRadius: 4 },
  msgText: { fontSize: 16, lineHeight: 22 },
  typing: { alignSelf: 'flex-start' },
  tools: { flexDirection: 'row', alignItems: 'center', gap: 5, marginTop: 4, marginLeft: 6 },
  chips: { gap: 8, paddingHorizontal: 2, paddingBottom: 10 },
  chip: { height: 36, paddingHorizontal: 14, borderRadius: 999, backgroundColor: C.card, borderWidth: 1, borderColor: C.line, justifyContent: 'center' },
  composer: { flexDirection: 'row', gap: 8, alignItems: 'center', paddingBottom: 12, paddingHorizontal: 2 },
  input: { flex: 1, height: 46, paddingHorizontal: 16, borderRadius: 999, backgroundColor: C.card, borderWidth: 1, borderColor: C.line,
    color: C.text, fontFamily: F.body, fontSize: 16 },
  send: { width: 46, height: 46, borderRadius: 23, backgroundColor: '#fff', alignItems: 'center', justifyContent: 'center' },
});

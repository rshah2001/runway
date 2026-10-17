/**
 * Who you are, and the way back out: "Maya · Switch" when looking around, "Maya · Sign out" when
 * signed in. Sits in the website's tab bar and at the top of Today on phones.
 */
import { useState } from 'react';
import { StyleSheet, Text } from 'react-native';

import { PressableScale } from '@/components/rw/ui';
import { C, F } from '@/constants/runway';
import { leave } from '@/lib/account';
import { useSession } from '@/lib/session';

export function AccountButton() {
  const session = useSession();
  const [leaving, setLeaving] = useState(false);
  if (session.mode !== 'guest' && session.mode !== 'signed-in') return null;
  const action = session.mode === 'signed-in' ? 'Sign out' : 'Switch';
  return (
    <PressableScale
      accessibilityRole="button"
      accessibilityLabel={session.mode === 'signed-in' ? `Signed in as ${session.name}. Sign out` : `Looking around as ${session.name}. Switch person`}
      disabled={leaving}
      onPress={async () => {
        setLeaving(true);
        try {
          await leave();
        } finally {
          setLeaving(false);
        }
      }}
      style={s.chip}>
      <Text style={s.name}>{session.name}</Text>
      <Text style={s.action}>{leaving ? '…' : action}</Text>
    </PressableScale>
  );
}

const s = StyleSheet.create({
  chip: {
    flexDirection: 'row', alignItems: 'center', gap: 8, paddingVertical: 7, paddingHorizontal: 12,
    borderRadius: 999, borderWidth: 1, borderColor: C.line, backgroundColor: C.card,
  },
  name: { fontFamily: F.bodySemi, fontSize: 14, color: C.text },
  action: { fontFamily: F.bodyMedium, fontSize: 13, color: C.text2 },
});

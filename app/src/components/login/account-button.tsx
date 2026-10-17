/**
 * Who you are, and the way out: "Maya · Sign out". Sits in the website's tab bar and at the top
 * of Today on phones.
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
  if (session.mode !== 'signed-in') return null;
  return (
    <PressableScale
      accessibilityRole="button"
      accessibilityLabel={`Signed in as ${session.name}. Sign out`}
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
      <Text style={s.action}>{leaving ? '…' : 'Sign out'}</Text>
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

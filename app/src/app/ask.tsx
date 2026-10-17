// Ask screen (agent chat + approve/decline cards) — owner: an2thu.
import { StyleSheet } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { Spacing } from '@/constants/theme';

export default function AskScreen() {
  return (
    <ThemedView style={styles.container}>
      <ThemedText type="subtitle">Ask Runway</ThemedText>
      <ThemedText themeColor="textSecondary">Chat with the agent — coming soon.</ThemedText>
    </ThemedView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: Spacing.four, paddingTop: Spacing.six * 1.5, gap: Spacing.three },
});

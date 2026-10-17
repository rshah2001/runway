// Spending screen (categories + subscription detective) — owner: an2thu.
import { StyleSheet } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { Spacing } from '@/constants/theme';

export default function SpendingScreen() {
  return (
    <ThemedView style={styles.container}>
      <ThemedText type="subtitle">Spending</ThemedText>
      <ThemedText themeColor="textSecondary">Categories and subscriptions — coming soon.</ThemedText>
    </ThemedView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: Spacing.four, paddingTop: Spacing.six * 1.5, gap: Spacing.three },
});

// Today screen — owner: Friend 1. Placeholder that proves the app ↔ backend wiring;
// replace with the runway chart, status card and "do this next" list (see prototype/).
import { useEffect, useState } from 'react';
import { ScrollView, StyleSheet } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { Spacing } from '@/constants/theme';
import { api } from '@/lib/api';
import type { Forecast } from '@/lib/types';

export default function TodayScreen() {
  const [forecast, setForecast] = useState<Forecast | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.forecast().then(setForecast).catch((e: Error) => setError(e.message));
  }, []);

  return (
    <ThemedView style={styles.container}>
      <ScrollView contentContainerStyle={styles.content}>
        <ThemedText type="subtitle">Runway</ThemedText>
        {error && <ThemedText themeColor="textSecondary">Backend not reachable: {error}</ThemedText>}
        {forecast && (
          <>
            <ThemedText>
              Tightest day: {forecast.low.date} at ${forecast.low.balance.toFixed(2)}
            </ThemedText>
            <ThemedText themeColor="textSecondary">
              {forecast.low.balance < forecast.safe_floor
                ? `Below your $${forecast.safe_floor} safety floor — a small move fixes it.`
                : "You're covered."}
            </ThemedText>
          </>
        )}
      </ScrollView>
    </ThemedView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  content: { padding: Spacing.four, paddingTop: Spacing.six * 1.5, gap: Spacing.three },
});

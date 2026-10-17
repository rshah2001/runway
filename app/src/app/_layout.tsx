import { Barlow_400Regular, Barlow_500Medium, Barlow_600SemiBold } from '@expo-google-fonts/barlow';
import { BarlowCondensed_500Medium, BarlowCondensed_600SemiBold, BarlowCondensed_700Bold, useFonts } from '@expo-google-fonts/barlow-condensed';
import { DarkTheme, ThemeProvider } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';
import { Platform } from 'react-native';

import AppTabs from '@/components/app-tabs';
import { C } from '@/constants/runway';

SplashScreen.preventAutoHideAsync();

// Runway is dark-only: the charcoal look is the brand, not a theme option.
const theme = { ...DarkTheme, colors: { ...DarkTheme.colors, background: C.bg, card: C.tabBar, text: C.text, border: C.line, primary: C.text } };

export default function RootLayout() {
  const [loaded, error] = useFonts({
    Barlow_400Regular, Barlow_500Medium, Barlow_600SemiBold,
    BarlowCondensed_500Medium, BarlowCondensed_600SemiBold, BarlowCondensed_700Bold,
  });

  // Keep the splash up until fonts are ready so text never flashes in a fallback face.
  useEffect(() => {
    if (loaded || error) SplashScreen.hideAsync();
  }, [loaded, error]);

  // Native waits behind the splash; the website renders right away (static HTML, then the font swaps in).
  if (!loaded && !error && Platform.OS !== 'web') return null;

  return (
    <ThemeProvider value={theme}>
      <StatusBar style="light" />
      <AppTabs />
    </ThemeProvider>
  );
}

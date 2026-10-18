import { Barlow_400Regular, Barlow_500Medium, Barlow_600SemiBold } from '@expo-google-fonts/barlow';
import { BarlowCondensed_500Medium, BarlowCondensed_600SemiBold, BarlowCondensed_700Bold, useFonts } from '@expo-google-fonts/barlow-condensed';
import { DarkTheme, ThemeProvider } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';
import { AppState, Platform } from 'react-native';

import AppTabs from '@/components/app-tabs';
import { LoginScreen } from '@/components/login/login-screen';
import { ApprovalSheet } from '@/components/rw/approval-sheet';
import { ChatLauncher } from '@/components/rw/chat';
import { C } from '@/constants/runway';
import { bootSession } from '@/lib/account';
import { useSession } from '@/lib/session';
import { moneyMoved, startAutoRefresh } from '@/lib/store';

SplashScreen.preventAutoHideAsync();

// Runway is dark-only: the charcoal look is the brand, not a theme option.
const theme = { ...DarkTheme, colors: { ...DarkTheme.colors, background: C.bg, card: C.tabBar, text: C.text, border: C.line, primary: C.text } };

export default function RootLayout() {
  const [loaded, error] = useFonts({
    Barlow_400Regular, Barlow_500Medium, Barlow_600SemiBold,
    BarlowCondensed_500Medium, BarlowCondensed_600SemiBold, BarlowCondensed_700Bold,
  });

  const session = useSession();
  useEffect(() => {
    bootSession(); // resume an Auth0 session or this tab's demo choice; otherwise the login screen
  }, []);

  // money moved by someone else (a payment, an approval, the safety net) shows up without a manual refresh
  useEffect(() => {
    if (session.mode !== 'signed-in') return;
    const stop = startAutoRefresh();
    const sub = AppState.addEventListener('change', (st) => st === 'active' && moneyMoved()); // phones: back to the app
    return () => {
      stop();
      sub.remove();
    };
  }, [session.mode]);

  // Keep the splash up until fonts are ready so text never flashes in a fallback face.
  useEffect(() => {
    if (loaded || error) SplashScreen.hideAsync();
  }, [loaded, error]);

  // Native waits behind the splash; the website renders right away (static HTML, then the font swaps in).
  if (!loaded && !error && Platform.OS !== 'web') return null;

  return (
    <ThemeProvider value={theme}>
      <StatusBar style="light" />
      {session.mode === 'checking' ? null : session.mode === 'signed-out' ? <LoginScreen /> : (
        <>
          <AppTabs />
          <ChatLauncher />
          <ApprovalSheet />
        </>
      )}
    </ThemeProvider>
  );
}

import { Barlow_400Regular, Barlow_500Medium, Barlow_600SemiBold } from '@expo-google-fonts/barlow';
import { BarlowCondensed_500Medium, BarlowCondensed_600SemiBold, BarlowCondensed_700Bold, useFonts } from '@expo-google-fonts/barlow-condensed';
import { DarkTheme, DefaultTheme, ThemeProvider } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';
import { AppState, Platform, View } from 'react-native';

import AppTabs from '@/components/app-tabs';
import { LoginScreen } from '@/components/login/login-screen';
import { ApprovalSheet } from '@/components/rw/approval-sheet';
import { InboxPopup } from '@/components/rw/inbox-popup';
import { ChatLauncher } from '@/components/rw/chat';
import { C } from '@/constants/runway';
import { bootSession } from '@/lib/account';
import { useSession } from '@/lib/session';
import { useAppearance } from '@/lib/theme';
import { moneyMoved, startAutoRefresh } from '@/lib/store';

SplashScreen.preventAutoHideAsync();

const colors = { background: C.bg, card: C.tabBar, text: C.text, border: C.line, primary: C.text };
const THEMES = {
  dark: { ...DarkTheme, colors: { ...DarkTheme.colors, ...colors } },
  light: { ...DefaultTheme, colors: { ...DefaultTheme.colors, ...colors } },
};
// The sign-in screen is a night airfield whatever the theme: its colour variables are pinned to dark.
const PIN_DARK = { dataSet: { theme: 'dark' } } as object;

export default function RootLayout() {
  const [loaded, error] = useFonts({
    Barlow_400Regular, Barlow_500Medium, Barlow_600SemiBold,
    BarlowCondensed_500Medium, BarlowCondensed_600SemiBold, BarlowCondensed_700Bold,
  });

  const session = useSession();
  const { scheme } = useAppearance();
  useEffect(() => {
    bootSession(); // resume an Auth0 session or this tab's demo choice; otherwise the login screen
  }, []);

  // money moved by someone else (a payment, an approval, the safety net) shows up without a manual refresh
  useEffect(() => {
    if (session.mode !== 'signed-in' && session.mode !== 'guest') return; // guests watch the demo move too
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
    <ThemeProvider value={THEMES[scheme]}>
      <StatusBar style={scheme === 'light' && (session.mode === 'signed-in' || session.mode === 'guest') ? 'dark' : 'light'} />
      {session.mode === 'checking' ? null : session.mode === 'signed-out' ? <View style={{ flex: 1 }} {...PIN_DARK}><LoginScreen /></View> : (
        <>
          <AppTabs />
          <ChatLauncher />
          <ApprovalSheet />
          <InboxPopup />
        </>
      )}
    </ThemeProvider>
  );
}

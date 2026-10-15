import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { Pressable, Text, View } from 'react-native';

import { supabase, supabaseConfigured } from '@/lib/supabase';
import { AuthProvider, useAuth } from '@/state/auth';
import { SessionProvider } from '@/state/session';
import { colors } from '@/theme';

export default function RootLayout() {
  return (
    <AuthProvider>
      <StatusBar style="light" />
      <RootStack />
    </AuthProvider>
  );
}

function RootStack() {
  const { session, loading } = useAuth();

  // Reading the saved login on launch; avoids flashing the login screen.
  if (loading) return <View style={{ flex: 1, backgroundColor: colors.background }} />;

  // Without Supabase keys in .env the login gate is skipped, so the app still runs.
  const signedIn = !supabaseConfigured || session !== null;

  return (
    // Keyed by user so picked videos and results reset when someone else signs in.
    <SessionProvider key={session?.user.id ?? 'signed-out'}>
      <Stack
        screenOptions={{
          headerStyle: { backgroundColor: colors.background },
          headerTintColor: colors.text,
          headerShadowVisible: false,
          contentStyle: { backgroundColor: colors.background },
        }}
      >
        <Stack.Protected guard={signedIn}>
          <Stack.Screen
            name="index"
            options={{
              title: 'StepSync',
              headerRight: supabaseConfigured ? () => <SignOutButton /> : undefined,
            }}
          />
          <Stack.Screen name="results" options={{ title: 'Feedback' }} />
          <Stack.Screen
            name="record"
            options={{ headerShown: false, presentation: 'fullScreenModal', animation: 'fade' }}
          />
        </Stack.Protected>

        <Stack.Protected guard={!signedIn}>
          <Stack.Screen name="login" options={{ headerShown: false }} />
        </Stack.Protected>
      </Stack>
    </SessionProvider>
  );
}

function SignOutButton() {
  return (
    <Pressable onPress={() => supabase.auth.signOut()} hitSlop={10}>
      <Text style={{ color: colors.accent, fontSize: 16, fontWeight: '600' }}>Sign out</Text>
    </Pressable>
  );
}

import { useState } from 'react';
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';

import { supabase } from '@/lib/supabase';
import { colors } from '@/theme';

type Mode = 'signIn' | 'signUp';

export default function LoginScreen() {
  const [mode, setMode] = useState<Mode>('signIn');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const signingUp = mode === 'signUp';

  async function onSubmit() {
    const trimmed = email.trim();
    setError(null);
    setNotice(null);
    if (!trimmed.includes('@')) return setError('Enter a valid email address.');
    if (password.length < 6) return setError('Password must be at least 6 characters.');

    setBusy(true);
    try {
      if (signingUp) {
        const { data, error } = await supabase.auth.signUp({ email: trimmed, password });
        if (error) throw error;
        // With email confirmation on (the Supabase default) there is no session yet.
        if (!data.session) {
          setNotice(`Check ${trimmed} for a confirmation link, then sign in here.`);
          setMode('signIn');
        }
      } else {
        const { error } = await supabase.auth.signInWithPassword({ email: trimmed, password });
        if (error) throw error;
      }
      // On success the auth listener updates the session and the app leaves this screen.
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong.');
    } finally {
      setBusy(false);
    }
  }

  function switchMode() {
    setMode(signingUp ? 'signIn' : 'signUp');
    setError(null);
    setNotice(null);
  }

  return (
    <KeyboardAvoidingView
      style={styles.fill}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <ScrollView contentContainerStyle={styles.container} keyboardShouldPersistTaps="handled">
        <View style={styles.brand}>
          <Text style={styles.logo}>StepSync</Text>
          <Text style={styles.tagline}>Learn the routine, one step at a time.</Text>
        </View>

        <Text style={styles.heading}>{signingUp ? 'Create an account' : 'Sign in'}</Text>

        <View style={styles.field}>
          <Text style={styles.label}>Email</Text>
          <TextInput
            value={email}
            onChangeText={setEmail}
            placeholder="you@example.com"
            placeholderTextColor={colors.muted}
            autoCapitalize="none"
            autoCorrect={false}
            autoComplete="email"
            keyboardType="email-address"
            textContentType="emailAddress"
            returnKeyType="next"
            style={styles.input}
          />
        </View>

        <View style={styles.field}>
          <Text style={styles.label}>Password</Text>
          <TextInput
            value={password}
            onChangeText={setPassword}
            placeholder={signingUp ? 'At least 6 characters' : 'Your password'}
            placeholderTextColor={colors.muted}
            secureTextEntry
            autoCapitalize="none"
            autoComplete={signingUp ? 'new-password' : 'current-password'}
            textContentType={signingUp ? 'newPassword' : 'password'}
            returnKeyType="go"
            onSubmitEditing={onSubmit}
            style={styles.input}
          />
        </View>

        {error && <Text style={styles.error}>{error}</Text>}
        {notice && <Text style={styles.notice}>{notice}</Text>}

        <Pressable
          onPress={onSubmit}
          disabled={busy}
          style={({ pressed }) => [styles.button, busy && styles.disabled, pressed && styles.pressed]}
        >
          {busy ? (
            <ActivityIndicator color={colors.text} />
          ) : (
            <Text style={styles.buttonText}>{signingUp ? 'Create account' : 'Sign in'}</Text>
          )}
        </Pressable>

        <Pressable onPress={switchMode} disabled={busy} hitSlop={8}>
          <Text style={styles.switch}>
            {signingUp ? 'Already have an account? ' : 'New to StepSync? '}
            <Text style={styles.switchLink}>{signingUp ? 'Sign in' : 'Create one'}</Text>
          </Text>
        </Pressable>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1, backgroundColor: colors.background },
  container: { flexGrow: 1, justifyContent: 'center', padding: 24, gap: 16 },
  brand: { alignItems: 'center', gap: 6, marginBottom: 24 },
  logo: { color: colors.text, fontSize: 36, fontWeight: '800', letterSpacing: -0.5 },
  tagline: { color: colors.muted, fontSize: 15 },
  heading: { color: colors.text, fontSize: 22, fontWeight: '700' },
  field: { gap: 6 },
  label: { color: colors.muted, fontSize: 14, fontWeight: '500' },
  input: {
    height: 50,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    paddingHorizontal: 14,
    color: colors.text,
    fontSize: 16,
  },
  error: { color: colors.bad, fontSize: 14 },
  notice: { color: colors.good, fontSize: 14, lineHeight: 20 },
  button: {
    height: 52,
    borderRadius: 14,
    backgroundColor: colors.accent,
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 4,
  },
  disabled: { opacity: 0.5 },
  pressed: { opacity: 0.8 },
  buttonText: { color: colors.text, fontSize: 17, fontWeight: '600' },
  switch: { color: colors.muted, textAlign: 'center', fontSize: 15 },
  switchLink: { color: colors.accent, fontWeight: '600' },
});

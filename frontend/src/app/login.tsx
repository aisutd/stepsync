import Ionicons from '@expo/vector-icons/Ionicons';
import { useState, type ComponentProps } from 'react';
import {
  Image,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
  type TextInputProps,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { PrimaryButton } from '@/components/primary-button';
import { supabase } from '@/lib/supabase';
import { setRememberMe } from '@/state/auth';
import { colors, radius } from '@/theme';

type Mode = 'logIn' | 'signUp';

export default function LoginScreen() {
  const insets = useSafeAreaInsets();
  const [mode, setMode] = useState<Mode>('logIn');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [remember, setRemember] = useState(true);
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
      await setRememberMe(remember);
      if (signingUp) {
        const { data, error } = await supabase.auth.signUp({ email: trimmed, password });
        if (error) throw error;
        // With email confirmation on (the Supabase default) there is no session yet.
        if (!data.session) {
          setNotice(`Check ${trimmed} for a confirmation link, then log in here.`);
          setMode('logIn');
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

  function notReady(feature: string) {
    setError(null);
    setNotice(`${feature} isn't set up yet. Use email and password for now.`);
  }

  function switchMode() {
    setMode(signingUp ? 'logIn' : 'signUp');
    setError(null);
    setNotice(null);
  }

  return (
    <KeyboardAvoidingView style={styles.fill} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView
        contentContainerStyle={[styles.container, { paddingTop: insets.top + 12, paddingBottom: insets.bottom + 24 }]}
        keyboardShouldPersistTaps="handled"
        showsVerticalScrollIndicator={false}
      >
        <Image
          source={require('../../assets/images/login-hero.png')}
          style={styles.hero}
          resizeMode="contain"
          accessibilityLabel="StepSync. Your dance journey starts here."
        />

        {signingUp && <Text style={styles.heading}>Create your account</Text>}

        <Field
          icon="person-outline"
          value={email}
          onChangeText={setEmail}
          placeholder="Email"
          autoCapitalize="none"
          autoCorrect={false}
          autoComplete="email"
          keyboardType="email-address"
          textContentType="emailAddress"
          returnKeyType="next"
        />
        <Field
          icon="lock-closed-outline"
          value={password}
          onChangeText={setPassword}
          placeholder="Password"
          secureTextEntry={!showPassword}
          autoCapitalize="none"
          autoComplete={signingUp ? 'new-password' : 'current-password'}
          textContentType={signingUp ? 'newPassword' : 'password'}
          returnKeyType="go"
          onSubmitEditing={onSubmit}
          trailing={
            <Pressable
              onPress={() => setShowPassword((s) => !s)}
              hitSlop={10}
              accessibilityLabel={showPassword ? 'Hide password' : 'Show password'}
            >
              <Ionicons name={showPassword ? 'eye-off-outline' : 'eye-outline'} size={20} color={colors.muted} />
            </Pressable>
          }
        />

        {!signingUp && (
          <View style={styles.options}>
            <Pressable onPress={() => setRemember((r) => !r)} hitSlop={8} style={styles.remember}>
              <Ionicons name={remember ? 'checkbox' : 'square-outline'} size={18} color={colors.text} />
              <Text style={styles.optionText}>Remember me</Text>
            </Pressable>
            <Pressable onPress={() => notReady('Password reset')} hitSlop={8}>
              <Text style={styles.optionText}>Forgot?</Text>
            </Pressable>
          </View>
        )}

        {error && <Text style={styles.error}>{error}</Text>}
        {notice && <Text style={styles.notice}>{notice}</Text>}

        <PrimaryButton label={signingUp ? 'Sign Up' : 'Log In'} onPress={onSubmit} loading={busy} />

        <View style={styles.dividerBlock}>
          <Text style={styles.continueWith}>or continue with</Text>
          <View style={styles.divider} />
        </View>

        <View style={styles.socialRow}>
          <SocialButton icon="logo-google" label="Google" onPress={() => notReady('Google sign-in')} />
          <SocialButton icon="logo-apple" label="Apple" onPress={() => notReady('Apple sign-in')} />
          <SocialButton icon="mail-outline" label="Email link" onPress={() => notReady('Email link sign-in')} />
        </View>

        <Pressable onPress={switchMode} disabled={busy} hitSlop={8} style={styles.footer}>
          <Text style={styles.footerText}>
            {signingUp ? 'Already have an account?  ' : "Don't have an account?  "}
            <Text style={styles.footerLink}>{signingUp ? 'Log In' : 'Sign Up'}</Text>
          </Text>
        </Pressable>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

type IconName = ComponentProps<typeof Ionicons>['name'];

function Field({ icon, trailing, ...input }: TextInputProps & { icon: IconName; trailing?: React.ReactNode }) {
  return (
    <View style={styles.field}>
      <Ionicons name={icon} size={18} color={colors.muted} />
      <TextInput {...input} placeholderTextColor={colors.muted} style={styles.input} />
      {trailing}
    </View>
  );
}

function SocialButton({ icon, label, onPress }: { icon: IconName; label: string; onPress: () => void }) {
  return (
    <Pressable
      onPress={onPress}
      accessibilityLabel={`Continue with ${label}`}
      style={({ pressed }) => [styles.social, pressed && styles.pressed]}
    >
      <Ionicons name={icon} size={22} color={colors.text} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1, backgroundColor: colors.background },
  container: { flexGrow: 1, paddingHorizontal: 24, gap: 14 },
  hero: { width: '100%', height: 300, marginBottom: 6 },
  heading: { color: colors.text, fontSize: 22, fontWeight: '700', marginBottom: 2 },
  field: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    height: 54,
    paddingHorizontal: 16,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  input: { flex: 1, height: '100%', color: colors.text, fontSize: 16 },
  options: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  remember: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  optionText: { color: colors.text, fontSize: 14 },
  error: { color: colors.bad, fontSize: 14, lineHeight: 20 },
  notice: { color: colors.accent, fontSize: 14, lineHeight: 20 },
  dividerBlock: { alignItems: 'center', gap: 10, marginTop: 4 },
  continueWith: { color: colors.muted, fontSize: 14 },
  divider: { alignSelf: 'stretch', height: 1, backgroundColor: colors.hairline },
  socialRow: { flexDirection: 'row', justifyContent: 'center', gap: 36, marginTop: 4 },
  social: {
    width: 52,
    height: 52,
    borderRadius: 26,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.surface,
  },
  pressed: { opacity: 0.7 },
  footer: { marginTop: 'auto', paddingTop: 24, alignItems: 'center' },
  footerText: { color: colors.muted, fontSize: 14 },
  footerLink: { color: colors.text, fontWeight: '600' },
});

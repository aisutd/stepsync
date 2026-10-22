import Ionicons from '@expo/vector-icons/Ionicons';
import { StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { PrimaryButton } from '@/components/primary-button';
import { supabase, supabaseConfigured } from '@/lib/supabase';
import { useAuth } from '@/state/auth';
import { colors } from '@/theme';

export default function ProfileScreen() {
  const insets = useSafeAreaInsets();
  const { session } = useAuth();
  const email = session?.user.email;

  return (
    <View style={[styles.container, { paddingTop: insets.top + 48 }]}>
      <View style={styles.avatar}>
        <Ionicons name="person-outline" size={40} color={colors.onPrimary} />
      </View>
      <Text style={styles.name}>{email ?? 'Guest'}</Text>
      <Text style={styles.caption}>
        {supabaseConfigured ? 'Signed in with email' : 'Login is off: Supabase keys are not in .env'}
      </Text>

      {supabaseConfigured && (
        <PrimaryButton
          label="Sign Out"
          arrow={false}
          onPress={() => supabase.auth.signOut()}
          style={styles.button}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, alignItems: 'center', gap: 8, paddingHorizontal: 24, backgroundColor: colors.background },
  avatar: {
    width: 96,
    height: 96,
    borderRadius: 48,
    backgroundColor: colors.primary,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 12,
  },
  name: { color: colors.text, fontSize: 20, fontWeight: '700' },
  caption: { color: colors.muted, fontSize: 14, textAlign: 'center' },
  button: { alignSelf: 'stretch', marginTop: 28 },
});

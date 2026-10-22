import Ionicons from '@expo/vector-icons/Ionicons';
import { StyleSheet, Text, View } from 'react-native';

import { colors } from '@/theme';

// Placeholder until the Explore screen is designed.
export default function ExploreScreen() {
  return (
    <View style={styles.container}>
      <Ionicons name="search-outline" size={40} color={colors.accentSoft} />
      <Text style={styles.title}>Explore</Text>
      <Text style={styles.body}>Browse new routines here. Coming soon.</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 10, padding: 32, backgroundColor: colors.background },
  title: { color: colors.text, fontSize: 24, fontWeight: '700' },
  body: { color: colors.muted, fontSize: 15, textAlign: 'center' },
});

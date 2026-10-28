import Ionicons from '@expo/vector-icons/Ionicons';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { PrimaryButton } from '@/components/primary-button';
import { grapevineCounts, lessonStepIndex } from '@/data/lesson';
import { lessonColors as palette, radius } from '@/theme';

export default function StepRecordingScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const params = useLocalSearchParams<{ step?: string }>();
  const step = lessonStepIndex(params.step);
  const count = grapevineCounts[step];
  const returnToStep = () => {
    if (router.canGoBack()) router.back();
    else router.replace({ pathname: '/steps', params: { step: String(step + 1) } });
  };

  return (
    <ScrollView style={styles.fill} contentContainerStyle={[styles.container, { paddingTop: insets.top + 20, paddingBottom: insets.bottom + 24 }]}>
      <View style={styles.content}>
        <Pressable accessibilityRole="button" accessibilityLabel="Back to step" onPress={returnToStep} style={({ pressed }) => [styles.back, pressed && styles.pressed]}>
          <Ionicons name="arrow-back" size={20} color={palette.text} />
        </Pressable>
        <Text style={styles.kicker}>THE GRAPEVINE · STEP {step + 1} OF {grapevineCounts.length}</Text>
        <Text accessibilityRole="header" style={styles.title}>Practice your step</Text>
        <Text style={styles.action}>{count.action.replace('\n', ' ')} · {count.foot}</Text>

        <View style={styles.preview}>
          <View style={styles.cameraIcon}><Ionicons name="videocam-outline" size={42} color={palette.accent} /></View>
          <Text style={styles.previewTitle}>Your recording will appear here</Text>
          <Text style={styles.description}>This is where you’ll record yourself doing this step. Recording is coming soon.</Text>
        </View>

        <PrimaryButton label="Back to step" onPress={returnToStep} arrow={false} style={styles.button} />
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1, backgroundColor: palette.background },
  container: { flexGrow: 1, alignItems: 'center', paddingHorizontal: 20 },
  content: { width: '100%', maxWidth: 350, gap: 16 },
  back: { width: 36, height: 36, alignItems: 'center', justifyContent: 'center', borderRadius: radius.pill, borderWidth: 1, borderColor: palette.border, backgroundColor: palette.surface, marginBottom: 12 },
  kicker: { fontSize: 10, fontWeight: '700', letterSpacing: 1.2, color: palette.accent },
  title: { fontSize: 32, lineHeight: 36, letterSpacing: -0.8, color: palette.text },
  action: { fontSize: 13, color: palette.secondary },
  preview: { minHeight: 332, borderRadius: 24, borderWidth: 1, borderStyle: 'dashed', borderColor: palette.border, backgroundColor: palette.surface, padding: 24, alignItems: 'center', justifyContent: 'center', gap: 16, marginVertical: 8 },
  cameraIcon: { width: 80, height: 80, borderRadius: radius.pill, backgroundColor: palette.selected, alignItems: 'center', justifyContent: 'center' },
  previewTitle: { fontSize: 18, fontWeight: '600', textAlign: 'center', color: palette.text },
  description: { fontSize: 14, lineHeight: 21, textAlign: 'center', color: palette.muted },
  button: { backgroundColor: palette.text, borderRadius: radius.pill },
  pressed: { opacity: 0.75 },
});

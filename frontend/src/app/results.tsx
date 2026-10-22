import { Redirect } from 'expo-router';
import { useVideoPlayer, VideoView } from 'expo-video';
import { FlatList, Pressable, StyleSheet, Text, View } from 'react-native';

import type { StepFeedback } from '@/api/types';
import { useSession } from '@/state/session';
import { colors, scoreColor } from '@/theme';

export default function ResultsScreen() {
  const { practice, result } = useSession();
  const player = useVideoPlayer(practice?.uri ?? null);

  if (!practice || !result) return <Redirect href="/" />;

  function jumpTo(step: StepFeedback) {
    player.currentTime = step.start;
    player.play();
  }

  return (
    <FlatList
      data={result.steps}
      keyExtractor={(step) => step.id}
      contentContainerStyle={styles.container}
      ListHeaderComponent={
        <View style={styles.header}>
          <VideoView player={player} style={styles.video} contentFit="contain" nativeControls />
          <View style={styles.overall}>
            <Text style={styles.overallLabel}>Overall match</Text>
            <Text style={[styles.overallScore, { color: scoreColor(result.overallScore) }]}>
              {result.overallScore}
            </Text>
          </View>
          <Text style={styles.hint}>Tap a step to jump to it in your video.</Text>
        </View>
      }
      renderItem={({ item }) => (
        <Pressable
          onPress={() => jumpTo(item)}
          style={({ pressed }) => [styles.step, pressed && styles.pressed]}
        >
          <View style={styles.stepTop}>
            <Text style={styles.stepLabel}>{item.label}</Text>
            <Text style={styles.time}>
              {formatTime(item.start)} to {formatTime(item.end)}
            </Text>
            <Text style={[styles.score, { color: scoreColor(item.score) }]}>{item.score}</Text>
          </View>
          <Text style={styles.feedback}>{item.feedback}</Text>
        </Pressable>
      )}
    />
  );
}

function formatTime(seconds: number): string {
  const whole = Math.floor(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`;
}

const styles = StyleSheet.create({
  container: { padding: 20, gap: 12 },
  header: { gap: 14, marginBottom: 4 },
  video: { width: '100%', aspectRatio: 16 / 9, borderRadius: 14, backgroundColor: '#000' },
  overall: { flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between' },
  overallLabel: { color: colors.text, fontSize: 18, fontWeight: '600' },
  overallScore: { fontSize: 34, fontWeight: '700', fontVariant: ['tabular-nums'] },
  hint: { color: colors.muted, fontSize: 13 },
  step: {
    padding: 14,
    borderRadius: 14,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    gap: 6,
  },
  pressed: { opacity: 0.7 },
  stepTop: { flexDirection: 'row', alignItems: 'baseline', gap: 10 },
  stepLabel: { color: colors.text, fontSize: 16, fontWeight: '600' },
  time: { flex: 1, color: colors.muted, fontSize: 13, fontVariant: ['tabular-nums'] },
  score: { fontSize: 18, fontWeight: '700', fontVariant: ['tabular-nums'] },
  feedback: { color: colors.text, fontSize: 15, lineHeight: 21 },
});

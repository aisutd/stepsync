import { useState } from 'react';
import { Redirect, useRouter } from 'expo-router';
import { useVideoPlayer, VideoView } from 'expo-video';
import { ActivityIndicator, FlatList, Pressable, StyleSheet, Text, View } from 'react-native';

import { analyze } from '@/api/client';
import type { MirrorMode, StepFeedback } from '@/api/types';
import { analysisPresentation } from '@/api/analysis-presentation';
import { CoachingChat } from '@/components/coaching-chat';
import { useSession } from '@/state/session';
import { colors, scoreColor } from '@/theme';

export default function ResultsScreen() {
  const { reference, practice, result, setResult } = useSession();
  const router = useRouter();
  const [retrying, setRetrying] = useState(false);
  const [retryProgress, setRetryProgress] = useState<number | null>(null);
  const [retryError, setRetryError] = useState<string | null>(null);
  const player = useVideoPlayer(practice?.uri ?? null);

  if (!practice || !result) return <Redirect href="/" />;
  const presentation = analysisPresentation(result);

  const mirrorSelection = result.alignment?.mirrorSelection;
  const showMirrorRetry = mirrorSelection?.ambiguous === true || mirrorSelection?.decision === 'undetermined'
    || (mirrorSelection?.requestedMode !== undefined && mirrorSelection.requestedMode !== 'auto');

  async function retry(mirrorMode: MirrorMode) {
    if (!reference || !practice || retrying) return;
    setRetrying(true);
    setRetryError(null);
    setRetryProgress(null);
    try {
      setResult(await analyze(reference, practice, setRetryProgress, mirrorMode));
    } catch (e) {
      setRetryError(e instanceof Error ? e.message : 'Could not retry analysis.');
    } finally {
      setRetrying(false);
    }
  }

  function jumpTo(step: StepFeedback) {
    player.currentTime = step.start;
    player.play();
  }

  return (
    <FlatList
      data={presentation.steps}
      keyExtractor={(step) => step.id}
      contentContainerStyle={styles.container}
      ListHeaderComponent={
        <View style={styles.header}>
          <VideoView player={player} style={styles.video} contentFit="contain" nativeControls />
          <View style={styles.overall}>
            <Text style={styles.overallLabel}>
              {presentation.globalScore !== null ? 'Assessed movement similarity' : 'Analysis-wide comparison unavailable'}
            </Text>
            {presentation.globalScore !== null && (
              <Text style={[styles.overallScore, { color: scoreColor(presentation.globalScore) }]}>
                {presentation.globalScore.toFixed(2)}
              </Text>
            )}
          </View>
          <Text style={styles.coverage}>{presentation.coverageText}</Text>
          {result.alignment?.mirrorSelection?.selectedMapping && <Text style={styles.hint}>
            Side matching: {result.alignment.mirrorSelection.selectedMapping === 'same' ? 'Same sides' : 'Mirrored sides'}
            {result.alignment.mirrorSelection.requestedMode === 'auto' ? ' (automatic)' : ' (manual)'}
          </Text>}
          <Text style={styles.hint}>{presentation.unassessedText}</Text>
          {presentation.partialScore !== null && (
            <View style={styles.partial}>
              <Text style={styles.overallLabel}>Assessed segments only</Text>
              <Text style={styles.partialScore}>Segment similarity: {presentation.partialScore.toFixed(2)}</Text>
              <Text style={styles.hint}>This score applies only to the supported segments below.</Text>
              {presentation.supported.map((span, index) => (
                <Text key={index} style={styles.hint}>{span.start.toFixed(3)}s to {span.end.toFixed(3)}s</Text>
              ))}
            </View>
          )}
          <Text style={styles.hint}>Similarity uses supported joint measurements, not every movement in the video.</Text>
          {presentation.globalScore === null && presentation.partialScore === null && (
            <Text style={styles.overallLabel}>Could not confidently assess these videos</Text>
          )}
          {result.reason ? <Text style={styles.hint}>{result.reason}</Text> : null}
          {result.warnings?.filter((warning) => warning !== result.reason).map((warning, index) => <Text key={index} style={styles.hint}>{warning}</Text>)}
          {showMirrorRetry && reference && (
            <View style={styles.partial}>
              <Text style={styles.overallLabel}>Check movement sides</Text>
              {mirrorSelection?.ambiguous && mirrorSelection.reason && <Text style={styles.hint}>{mirrorSelection.reason}</Text>}
              <Text style={styles.hint}>Automatic side matching may be uncertain. Choose the intended convention: same matches left to left; mirrored matches your left to the right side of the reference dancer. This setting does not guarantee a reliable comparison.</Text>
              {mirrorSelection?.requestedMode && <Text style={styles.hint}>Current setting: {mirrorSelection.requestedMode}</Text>}
              <Pressable accessibilityRole="button" disabled={retrying} onPress={() => void retry('same')} style={styles.retry}>
                <Text style={styles.feedback}>Retry: same sides</Text>
              </Pressable>
              <Pressable accessibilityRole="button" disabled={retrying} onPress={() => void retry('mirrored')} style={styles.retry}>
                <Text style={styles.feedback}>Retry: mirrored sides</Text>
              </Pressable>
              <Text style={styles.hint}>Retry uploads both selected videos and runs analysis again.</Text>
            </View>
          )}
          {retrying && <View accessibilityLiveRegion="polite" style={styles.partial}>
            <ActivityIndicator color={colors.primary} />
            <Text style={styles.feedback}>{retryProgress === null ? 'Preparing videos...' : retryProgress < 1 ? `Uploading ${Math.round(retryProgress * 100)}%` : 'Analyzing...'} Keep this page open.</Text>
            <Text style={styles.hint}>The results below are from the previous analysis until this retry finishes.</Text>
          </View>}
          {retryError && <Text accessibilityRole="alert" style={styles.error}>{retryError} The previous results remain below.</Text>}
          <Pressable accessibilityRole="button" disabled={retrying} onPress={() => router.replace('/practice')} style={styles.retry}>
            <Text style={styles.feedback}>Choose different videos</Text>
          </Pressable>
          {presentation.steps.length > 0 && <Text style={styles.hint}>Tap a reported difference to jump to it in your video.</Text>}
        </View>
      }
      ListEmptyComponent={
        <Text style={styles.hint}>No supported movement differences to display. Unassessed movements have no correctness result.</Text>
      }
      ListFooterComponent={result.sessionId ? <CoachingChat key={result.sessionId} sessionId={result.sessionId} disabled={retrying} /> : null}
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
  overallLabel: { color: colors.text, fontSize: 18, fontWeight: '600', flexShrink: 1 },
  overallScore: { fontSize: 34, fontWeight: '700', fontVariant: ['tabular-nums'] },
  coverage: { color: colors.text, fontSize: 15, fontWeight: '600' },
  partial: { backgroundColor: colors.surface, borderRadius: 14, padding: 14, gap: 8 },
  partialScore: { color: colors.text, fontSize: 18, fontWeight: '600' },
  retry: { padding: 12, borderRadius: 10, backgroundColor: colors.pill },
  error: { color: colors.bad, fontSize: 14 },
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

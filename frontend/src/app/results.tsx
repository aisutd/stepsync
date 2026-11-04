import { Redirect, useRouter } from 'expo-router';
import { useVideoPlayer, VideoView } from 'expo-video';
import { FlatList, Pressable, StyleSheet, Text, View } from 'react-native';

import type { StepFeedback } from '@/api/types';
import { analysisPresentation } from '@/api/analysis-presentation';
import { CoachingChat } from '@/components/coaching-chat';
import { useSession } from '@/state/session';
import { colors, scoreColor } from '@/theme';

export default function ResultsScreen() {
  const router = useRouter();
  const { reference, practice, result, currentStep, completedSteps, markStepCompleted, setCurrentStep, setPractice, setResult } = useSession();
  const tutorialSteps = reference?.youtube?.steps ?? [];
  const hasStepSequence = tutorialSteps.length > 0;
  const verifiedScore = result?.scoreAvailable === undefined || (result.scoreAvailable && result.globalScoreAvailable && result.status === 'completed');
  const passed = Boolean(result && verifiedScore && Number.isFinite(result.overallScore) && result.overallScore > 80);
  const canAdvance = passed && hasStepSequence && currentStep < tutorialSteps.length - 1;
  const canComplete = passed && hasStepSequence && currentStep === tutorialSteps.length - 1;
  const player = useVideoPlayer(practice?.uri ?? null);

  if (!practice || !result) return <Redirect href="/" />;

  const detailed = typeof result.scoreAvailable === 'boolean';
  const presentation = detailed ? analysisPresentation(result) : null;

  function advance() {
    if (!result || !passed || !hasStepSequence) return;
    markStepCompleted(currentStep);
    if (canAdvance) {
      setCurrentStep(currentStep + 1);
      setPractice(null);
      setResult(null);
      router.replace('/practice');
    }
  }

  function jumpTo(step: StepFeedback) {
    player.currentTime = step.start;
    player.play();
  }

  return (
    <FlatList
      data={detailed ? presentation!.steps : result.steps}
      keyExtractor={(step) => step.id}
      contentContainerStyle={styles.container}
      ListHeaderComponent={
        <View style={styles.header}>
          <VideoView player={player} style={styles.video} contentFit="contain" nativeControls />
          <View style={styles.overall}>
            <Text style={styles.overallLabel}>{detailed ? (presentation!.globalScore !== null ? "Assessed movement similarity" : "Comparison coverage") : "Overall DTW score"}</Text>
            {(!detailed || presentation!.globalScore !== null) && (
              <Text style={[styles.overallScore, { color: scoreColor(detailed ? presentation!.globalScore! : result.overallScore) }]}>
                {detailed ? presentation!.globalScore!.toFixed(2) : result.overallScore}
              </Text>
            )}
          </View>
          {detailed && <Text style={styles.hint}>{presentation!.coverageText}. {presentation!.unassessedText}</Text>}
          {detailed && presentation!.partialScore !== null && (
            <Text style={styles.hint}>Supported segments only: {presentation!.partialScore.toFixed(2)}. This is not a whole-dance score.</Text>
          )}
          {detailed && result.reason && <Text style={styles.hint}>{result.reason}</Text>}
          {(!detailed || presentation!.globalScore !== null) && <Text style={styles.hint}>Timing score: {result.timingScore ?? 'N/A'} · Pass threshold: over 80/100</Text>}
          <View style={[styles.passBox, passed ? styles.passSuccess : styles.passRetry]}>
            <Text style={styles.passTitle}>{passed ? '✓ Step passed!' : 'Try this step again'}</Text>
            <Text style={styles.passBody}>{passed ? 'Your combined movement and timing score is above 80.' : 'You need an overall DTW score greater than 80 to unlock the next step.'}</Text>
          </View>
          {hasStepSequence && (
            <Pressable onPress={advance} disabled={!canAdvance && !canComplete} style={[styles.nextButton, !passed && styles.nextDisabled]}>
              <Text style={styles.nextText}>{canAdvance ? `Next Step → ${tutorialSteps[currentStep + 1]?.label ?? ''}` : canComplete ? '✓ Finish this dance' : '🔒 Next step locked (score > 80)'}</Text>
            </Pressable>
          )}
          {canComplete && <Text style={styles.hint}>You passed the final step! Tap Finish to mark it complete.</Text>}
          {passed && hasStepSequence && completedSteps.includes(currentStep) && <Text style={styles.hint}>This step is marked complete.</Text>}
          <Text style={styles.timelineTitle}>Mistake timeline</Text>
          <Text style={styles.hint}>Red and amber marks show lower-scoring moments. Tap any marker to replay that moment. Scores are heuristic pose comparisons.</Text>
          <MistakeTimeline steps={detailed ? presentation!.steps : result.steps} duration={Math.max(practice.durationMs ? practice.durationMs / 1000 : 0, ...result.steps.map(s => s.end), 1)} onJump={jumpTo} />
          <Text style={styles.hint}>Tap a feedback section below to replay it.</Text>
        </View>
      }
      ListFooterComponent={detailed && result.sessionId ? <CoachingChat key={result.sessionId} sessionId={result.sessionId} /> : null}
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

function MistakeTimeline({ steps, duration, onJump }: { steps: StepFeedback[]; duration: number; onJump: (step: StepFeedback) => void }) {
  const mistakes = steps.filter(s => s.score <= 80 && Number.isFinite(s.start));
  return <View style={styles.timelineContainer}>
    <View style={styles.timelineBar}>
      {mistakes.map((step, idx) => {
        const position = Math.min(95, Math.max(1, (step.start / duration) * 100));
        return <Pressable key={`${step.id}-${idx}`} accessibilityLabel={`Mistake at ${formatTime(step.start)}: ${step.feedback}`}
          onPress={() => onJump(step)} style={[styles.timelineMark, { left: `${position}%`, backgroundColor: step.score < 60 ? colors.bad : colors.okay }]} />;
      })}
    </View>
    <View style={styles.timeLabels}><Text style={styles.hint}>0:00</Text><Text style={styles.hint}>{formatTime(duration)}</Text></View>
    {mistakes.length === 0 ? <Text style={styles.hint}>No low-scoring intervals detected in the assessed footage.</Text> :
      mistakes.map((step, idx) => <Pressable key={`${step.id}-issue-${idx}`} onPress={() => onJump(step)} style={styles.mistakeRow}>
        <Text style={styles.mistakeTime}>{formatTime(step.start)}</Text>
        <Text style={styles.mistakeText}>{step.feedback} ({step.score}/100)</Text>
      </Pressable>)}
  </View>;
}

function formatTime(seconds: number): string {
  const whole = Math.floor(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`;
}

const styles = StyleSheet.create({
  container: { padding: 20, gap: 12 },
  header: { gap: 14, marginBottom: 4 },
  timelineTitle: { fontSize: 20, fontWeight: '700', color: colors.text, marginTop: 5 },
  timelineContainer: { backgroundColor: colors.surface, padding: 14, borderRadius: 14, gap: 12 },
  timelineBar: { height: 15, backgroundColor: colors.hairline, borderRadius: 10, marginTop: 7, position: 'relative' },
  timelineMark: { position: 'absolute', width: 12, height: 28, top: -6, borderRadius: 5 },
  timeLabels: { flexDirection: 'row', justifyContent: 'space-between' },
  mistakeRow: { flexDirection: 'row', alignItems: 'flex-start', gap: 10, paddingTop: 7, borderTopWidth: 1, borderTopColor: colors.hairline },
  mistakeTime: { color: colors.bad, fontWeight: '700', width: 42 },
  mistakeText: { flex: 1, color: colors.text, fontSize: 13 },
  passBox: { borderRadius: 12, padding: 14, gap: 5, borderWidth: 1 },
  passSuccess: { backgroundColor: '#E4F2E9', borderColor: colors.good },
  passRetry: { backgroundColor: '#FBF0E6', borderColor: colors.okay },
  passTitle: { fontSize: 17, fontWeight: '700', color: colors.text },
  passBody: { color: colors.text, fontSize: 13 },
  nextButton: { backgroundColor: colors.good, borderRadius: 12, padding: 16, alignItems: 'center' },
  nextDisabled: { backgroundColor: colors.muted, opacity: 0.6 },
  nextText: { color: '#fff', fontWeight: '700', fontSize: 15 },
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

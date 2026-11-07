import { useCallback, useRef, useState } from 'react';
import { Redirect, useFocusEffect, useRouter } from 'expo-router';
import { useVideoPlayer, VideoView } from 'expo-video';
import { ActivityIndicator, Linking, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { analysisDiagnosticsUrl, retryAnalysis } from '@/api/client';
import type { MirrorMode, StepFeedback } from '@/api/types';
import { analysisPresentation } from '@/api/analysis-presentation';
import { CoachingChat } from '@/components/coaching-chat';
import { useSession } from '@/state/session';
import { colors, scoreColor } from '@/theme';

export default function ResultsScreen() {
  const { reference, practice, result, beginResultRequest, currentStep, setCurrentStep, markStepCompleted, setPractice, setResult } = useSession();
  const router = useRouter();
  const retryInFlight = useRef<object | null>(null);
  const focused = useRef(false);
  const [showTechnical, setShowTechnical] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [retryProgress, setRetryProgress] = useState<number | null>(null);
  const [retryError, setRetryError] = useState<string | null>(null);
  const player = useVideoPlayer(practice?.uri ?? null);
  useFocusEffect(useCallback(() => {
    focused.current = true;
    setRetrying(false);
    setRetryError(null);
    setRetryProgress(null);
    return () => {
      focused.current = false;
      retryInFlight.current = null;
    };
  }, []));

  if (!practice || !result) return <Redirect href="/" />;
  const presentation = analysisPresentation(result);

  const tutorialSteps = reference?.youtube?.steps ?? [];
  const stepMode = currentStep !== null && currentStep < tutorialSteps.length;
  const passed = presentation.globalScore !== null && presentation.globalScore > 80;
  function returnToPractice(advance: boolean) {
    if (advance && passed && stepMode) {
      markStepCompleted(currentStep!);
      if (currentStep! < tutorialSteps.length - 1) setCurrentStep(currentStep! + 1);
    }
    setPractice(null);
    setResult(null);
    if (router.canGoBack()) router.back();
    else router.replace('/practice');
  }

  const mirrorSelection = result.alignment?.mirrorSelection;


  async function retry(mirrorMode: Exclude<MirrorMode, 'auto'>) {
    if (!result || !focused.current || retryInFlight.current) return;
    const token = {};
    retryInFlight.current = token;
    const request = beginResultRequest();
    const visible = () => focused.current && retryInFlight.current === token;
    setRetrying(true);
    setRetryError(null);
    setRetryProgress(null);
    try {
      const next = await retryAnalysis(result.sessionId, mirrorMode, reference, practice, progress => {
        if (visible() && request.isCurrent()) setRetryProgress(progress);
      }, stepMode ? tutorialSteps[currentStep!] : undefined);
      if (visible()) request.commit(next);
    } catch (e) {
      if (visible() && request.isCurrent()) setRetryError(e instanceof Error ? e.message : 'Could not retry analysis.');
    } finally {
      if (visible()) {
        retryInFlight.current = null;
        setRetrying(false);
      }
    }
  }

  function jumpTo(step: StepFeedback) {
    player.currentTime = step.start;
    player.play();
  }

  const sideChoice = (
    <View style={styles.sideChoice}>
      <Text accessibilityRole="header" style={styles.overallLabel}>
        Optional movement sides
      </Text>
      <Text style={styles.feedback}>Automatic matching is the default. If you know your intended convention, you can refine this comparison using saved pose measurements.</Text>
      <Text style={styles.hint}>Same sides: your left follows the dancer's left. Mirror movements: your left follows their right.</Text>
      <Text style={styles.hint}>Choose your intention, not the higher score. Your choice does not guarantee reliable alignment.</Text>
      <Pressable accessibilityRole="button" disabled={retrying} onPress={() => void retry('same')} style={styles.retry}>
        <Text style={styles.feedback}>Same sides</Text>
      </Pressable>
      <Pressable accessibilityRole="button" disabled={retrying} onPress={() => void retry('mirrored')} style={styles.retry}>
        <Text style={styles.feedback}>Mirror movements</Text>
      </Pressable>
    </View>
  );
  const similarity = presentation.globalScore ?? presentation.partialScore;

  return (
    <ScrollView contentContainerStyle={styles.container}>
      <Text accessibilityRole="header" style={styles.title}>Your dance check-in</Text>
      {stepMode && <View style={styles.partial}>
        <Text style={styles.overallLabel}>Step {currentStep! + 1}: {passed ? 'Step passed!' : 'Try this step again'}</Text>
        <Text style={styles.hint}>A reliable movement score over 80 unlocks the next step.</Text>
        <Pressable disabled={retrying} onPress={() => returnToPractice(passed)} style={styles.retry}>
          <Text style={styles.feedback}>{passed ? currentStep === tutorialSteps.length - 1 ? 'Finish this dance' : 'Next step' : 'Record this step again'}</Text>
        </Pressable>
      </View>}
      {retrying && <View accessibilityLiveRegion="polite" style={styles.partial}>
        <ActivityIndicator color={colors.primary} />
        <Text style={styles.feedback}>{retryProgress === null ? 'Comparing saved movements...' : retryProgress < 1 ? `Uploading ${Math.round(retryProgress * 100)}%` : 'Analyzing...'} Keep this page open.</Text>
        <Text style={styles.hint}>Your previous results stay here until the comparison finishes.</Text>
      </View>}
      {retryError && <Text accessibilityRole="alert" style={styles.error}>{retryError} Your previous results are saved.</Text>}
      {result.sessionId
        ? <CoachingChat key={result.sessionId} sessionId={result.sessionId} disabled={retrying} technicalDetails={showTechnical} />
        : <Text style={styles.hint}>Connect to the backend to receive saved, evidence-based coaching.</Text>}
      <View style={styles.partial}>
        {similarity !== null && <View style={styles.overall}>
          <Text style={styles.overallLabel}>{presentation.partialScore !== null ? 'Supported-section similarity' : 'Movement similarity'}</Text>
          <Text style={[styles.overallScore, { color: scoreColor(similarity) }]}>{similarity.toFixed(1)} / 100</Text>
        </View>}
        <Text style={styles.hint}>{presentation.scopeNote}</Text>
      </View>
      <Pressable accessibilityRole="button" accessibilityState={{ expanded: showTechnical }} disabled={retrying}
        onPress={() => setShowTechnical(!showTechnical)} style={styles.retry}>
        <Text style={styles.feedback}>{showTechnical ? 'Hide technical details' : 'View technical details'}</Text>
      </Pressable>
      {showTechnical && <View style={styles.details}>
        <Text accessibilityRole="header" style={styles.overallLabel}>Analysis details</Text>
        <Text selectable style={styles.hint}>{presentation.coverageText}</Text>
        <Text style={styles.hint}>{presentation.unassessedText}</Text>
        {mirrorSelection?.requestedMode && <Text style={styles.hint}>Side setting: {mirrorSelection.requestedMode}; selected mapping: {mirrorSelection.selectedMapping ?? 'unconfirmed'}</Text>}
        {result.reason && <Text selectable style={styles.hint}>{result.reason}</Text>}
        {result.warnings?.filter(warning => warning !== result.reason).map((warning, index) => <Text selectable key={index} style={styles.hint}>{warning}</Text>)}
        {sideChoice}
        <VideoView player={player} style={styles.video} contentFit="contain" nativeControls />
        {presentation.supported.map((span, index) => <Text key={index} style={styles.hint}>Supported span: {span.start.toFixed(3)}s to {span.end.toFixed(3)}s</Text>)}
        {presentation.steps.map(step => <Pressable key={step.id} accessibilityRole="button" onPress={() => jumpTo(step)} style={styles.step}>
          <Text style={styles.overallLabel}>{step.label}</Text>
          <Text style={styles.hint}>{formatTime(step.start)} to {formatTime(step.end)}; measured similarity: {step.score}</Text>
          <Text selectable style={styles.feedback}>{step.feedback}</Text>
        </Pressable>)}
        {result.sessionId && <Pressable accessibilityRole="link" onPress={() => void Linking.openURL(analysisDiagnosticsUrl(result.sessionId!))} style={styles.retry}>
          <Text style={styles.feedback}>Download full diagnostic JSON</Text>
        </Pressable>}
        <Text style={styles.hint}>Full measurements and paginated frame records remain available through the backend API. Downloads are requested only when you open them.</Text>
      </View>}
      <Pressable accessibilityRole="button" disabled={retrying} onPress={() => returnToPractice(false)} style={styles.retry}>
        <Text style={styles.feedback}>Compare new videos</Text>
      </Pressable>
    </ScrollView>
  );
}

function formatTime(seconds: number): string {
  const whole = Math.floor(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`;
}

const styles = StyleSheet.create({
  container: { padding: 20, paddingBottom: 40, gap: 20, width: '100%', maxWidth: 720, alignSelf: 'center' },
  title: { color: colors.text, fontSize: 28, fontWeight: '700' },
  details: { gap: 14, borderTopWidth: 1, borderTopColor: colors.border, paddingTop: 16 },
  video: { width: '100%', aspectRatio: 16 / 9, borderRadius: 14, backgroundColor: '#000' },
  overall: { flexDirection: 'row', flexWrap: 'wrap', gap: 12, alignItems: 'baseline', justifyContent: 'space-between' },
  overallLabel: { color: colors.text, fontSize: 18, fontWeight: '600', flexShrink: 1 },
  overallScore: { fontSize: 26, fontWeight: '700', fontVariant: ['tabular-nums'] },
  coverage: { color: colors.text, fontSize: 15, fontWeight: '600' },
  sideChoice: { borderWidth: 2, borderColor: colors.primary, backgroundColor: colors.surface, borderRadius: 14, padding: 16, gap: 12 },
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

import * as ImagePicker from 'expo-image-picker';
import { useRouter } from 'expo-router';
import { useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { analyze, analyzeDetailed, usingMockApi } from '@/api/client';
import type { PickedVideo } from '@/api/types';
import { VideoSlot } from '@/components/video-slot';
import { useSession } from '@/state/session';
import { colors } from '@/theme';

export default function HomeScreen() {
  const router = useRouter();
  const { reference, practice, setReference, setPractice, setResult, currentStep, completedSteps, setCurrentStep } = useSession();
  const steps = reference?.youtube?.steps ?? [];
  const selected = steps[currentStep];
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const ready = reference !== null && practice !== null && !loading;

  async function onAnalyze(detailed = false) {
    if (!reference || !practice) return;
    if (detailed && selected) { setError("Detailed coaching currently compares the complete reference. Use DTW to score an individual step."); return; }
    setLoading(true);
    setError(null);
    setProgress(null);
    try {
      setResult(await (detailed ? analyzeDetailed(reference, practice, setProgress) : analyze(reference, practice, setProgress, selected)));
      router.push('/results');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong.');
    } finally {
      setLoading(false);
      setProgress(null);
    }
  }

  return (
    <ScrollView contentContainerStyle={styles.container}>
      <Text style={styles.lead}>
        Add the routine you are learning and a take of you dancing it. Record one now or choose a saved video.
      </Text>

      <VideoSlot
        title="Reference video"
        hint="The choreography you want to learn"
        video={reference}
        onChoose={async () => { const chosen = await pickVideo(); if (chosen) setReference(chosen); }}
        onRecord={canRecord ? () => router.push('/record?slot=reference') : undefined}
        onYouTube={() => router.push('/youtube?from=practice')}
      />
      {steps.length > 0 && (
        <View style={styles.stepPanel}>
          <Text style={styles.stepHeading}>Tutorial step {currentStep + 1} of {steps.length}</Text>
          <Text style={styles.stepTitle}>{selected?.label}</Text>
          <Text style={styles.stepHelp}>Tutorial {formatSeconds((selected?.start_ms ?? 0) / 1000)}–{formatSeconds((selected?.end_ms ?? 0) / 1000)}. Record yourself performing just this step, then compare with DTW.</Text>
          <View style={styles.stepDots}>
            {steps.map((step, i) => (
              <Pressable key={`${step.step_index}-${i}`} accessibilityLabel={`Step ${i + 1}`} onPress={() => { if (i === currentStep || completedSteps.includes(i - 1)) { setCurrentStep(i); setPractice(null); setResult(null); } }}
                disabled={!(i === currentStep || completedSteps.includes(i - 1))}
                style={[styles.stepDot, i === currentStep && styles.stepDotActive, completedSteps.includes(i) && styles.stepDotPassed]}>
                <Text style={[styles.stepDotText, (i === currentStep || completedSteps.includes(i)) && styles.stepDotTextActive]}>{completedSteps.includes(i) ? '✓' : i + 1}</Text>
              </Pressable>
            ))}
          </View>
        </View>
      )}
      <VideoSlot
        title="Practice video"
        hint="Your attempt"
        video={practice}
        onChoose={async () => { const chosen = await pickVideo(); if (chosen) setPractice(chosen); }}
        onRecord={canRecord ? () => router.push('/record?slot=practice') : undefined}
      />

      <Pressable onPress={() => router.push('/record?slot=practice')} disabled={loading} style={[styles.recordButton, loading && styles.disabled]}>
        <Text style={styles.recordText}>● Record practice</Text>
      </Pressable>
      <Text style={styles.note}>Use your phone camera, or record in a supported desktop browser. You can also choose a saved video above.</Text>
      <Pressable
        onPress={() => void onAnalyze(false)}
        disabled={!ready}
        style={({ pressed }) => [styles.button, !ready && styles.disabled, pressed && styles.pressed]}
      >
        {loading ? (
          <View style={styles.loadingRow}>
            <ActivityIndicator color={colors.onPrimary} />
            {progress !== null && (
              <Text style={styles.buttonText}>
                {progress < 1 ? `Uploading ${Math.round(progress * 100)}%` : 'Analyzing…'}
              </Text>
            )}
          </View>
        ) : (
          <Text style={styles.buttonText}>{selected ? `Score step ${currentStep + 1} with DTW` : "Analyze with DTW"}</Text>
        )}
      </Pressable>

      {!reference?.youtube && steps.length === 0 && (
        <Pressable onPress={() => void onAnalyze(true)} disabled={!ready}
          style={({ pressed }) => [styles.button, { backgroundColor: colors.accent }, !ready && styles.disabled, pressed && styles.pressed]}>
          <Text style={styles.buttonText}>Detailed movement analysis + AI coach</Text>
        </Pressable>
      )}
      {reference?.youtube && <Text style={styles.note}>Detailed coaching currently requires a local reference video. YouTube imports use DTW.</Text>}
      {error && <Text style={styles.error}>{error}</Text>}
      {usingMockApi && (
        <Text style={styles.note}>Mock mode: feedback is sample data, nothing is uploaded.</Text>
      )}
    </ScrollView>
  );
}

// Native camera route is provided by record.tsx; browsers use record.web.tsx.
const canRecord = true;
function formatSeconds(seconds: number) { const n = Math.floor(seconds); return `${Math.floor(n/60)}:${String(n%60).padStart(2,'0')}`; }

async function pickVideo(): Promise<PickedVideo | null> {
  const picked = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ['videos'] });
  if (picked.canceled) return null;

  const asset = picked.assets[0];
  return {
    uri: asset.uri,
    fileName: asset.fileName ?? asset.uri.split('/').pop() ?? 'video.mp4',
    mimeType: asset.mimeType ?? 'video/mp4',
    durationMs: asset.duration ?? null,
  };
}

const styles = StyleSheet.create({
  container: { padding: 20, paddingBottom: 120, gap: 16 },
  lead: { color: colors.muted, fontSize: 16, lineHeight: 22, marginBottom: 4 },
  button: {
    height: 52,
    borderRadius: 14,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.primary,
    marginTop: 8,
  },
  disabled: { opacity: 0.4 },
  pressed: { opacity: 0.8 },
  loadingRow: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  buttonText: { color: colors.onPrimary, fontSize: 17, fontWeight: '600' },
  error: { color: colors.bad, fontSize: 14 },
  note: { color: colors.muted, fontSize: 13, textAlign: 'center' },
  recordButton: { backgroundColor: '#B32632', borderRadius: 14, padding: 16, alignItems: 'center' },
  recordText: { color: '#fff', fontSize: 16, fontWeight: '700' },
  stepPanel: { backgroundColor: colors.surface, borderRadius: 14, padding: 16, gap: 7, borderWidth: 1, borderColor: colors.border },
  stepHeading: { fontSize: 13, color: colors.muted, fontWeight: '700' },
  stepTitle: { fontSize: 19, color: colors.text, fontWeight: '700' },
  stepHelp: { color: colors.muted, fontSize: 13, lineHeight: 19 },
  stepDots: { flexDirection: 'row', gap: 7, flexWrap: 'wrap', marginTop: 5 },
  stepDot: { width: 34, height: 34, borderRadius: 17, backgroundColor: colors.pill, justifyContent: 'center', alignItems: 'center' },
  stepDotActive: { backgroundColor: colors.primary },
  stepDotPassed: { backgroundColor: colors.good },
  stepDotText: { color: colors.muted, fontWeight: '700' },
  stepDotTextActive: { color: '#fff' },
});

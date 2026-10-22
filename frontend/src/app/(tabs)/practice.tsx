import * as ImagePicker from 'expo-image-picker';
import { useRouter } from 'expo-router';
import { useState } from 'react';
import { ActivityIndicator, Platform, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { analyze, usingMockApi } from '@/api/client';
import type { PickedVideo } from '@/api/types';
import { VideoSlot } from '@/components/video-slot';
import { useSession } from '@/state/session';
import { colors } from '@/theme';

export default function HomeScreen() {
  const router = useRouter();
  const { reference, practice, setReference, setPractice, setResult } = useSession();
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const ready = reference !== null && practice !== null && !loading;

  async function onAnalyze() {
    if (!reference || !practice) return;
    setLoading(true);
    setError(null);
    setProgress(null);
    try {
      setResult(await analyze(reference, practice, setProgress));
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
        hint="The choreography you want to match"
        video={reference}
        onChoose={async () => setReference((await pickVideo()) ?? reference)}
        onRecord={canRecord ? () => router.push('/record?slot=reference') : undefined}
      />
      <VideoSlot
        title="Practice video"
        hint="Your attempt"
        video={practice}
        onChoose={async () => setPractice((await pickVideo()) ?? practice)}
        onRecord={canRecord ? () => router.push('/record?slot=practice') : undefined}
      />

      <Pressable
        onPress={onAnalyze}
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
          <Text style={styles.buttonText}>Analyze</Text>
        )}
      </Pressable>

      {error && <Text style={styles.error}>{error}</Text>}
      {usingMockApi && (
        <Text style={styles.note}>Mock mode: feedback is sample data, nothing is uploaded.</Text>
      )}
    </ScrollView>
  );
}

// expo-camera can only record in the native app, not the browser.
const canRecord = Platform.OS !== 'web';

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
});
